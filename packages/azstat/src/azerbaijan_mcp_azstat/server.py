"""FastMCP server for the statistical tables of the State Statistical Committee."""

from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from . import catalogue, tables
from .client import TABLE_ID, AzstatClient
from .errors import AzstatError, TableTooLarge
from .models import (
    DimensionInfo,
    Status,
    TableData,
    TableDescription,
    TableSearch,
    TableSummary,
    Topic,
    TopicList,
)

SOURCE_URL = "https://www.azstat.gov.az"
TABLE_URL = "https://www.azstat.gov.az/statHtml/statHtml.do?orgId=994&tblId={table_id}"
ATTRIBUTION = (
    "Source: State Statistical Committee of the Republic of Azerbaijan (azstat.gov.az), "
    "open data API."
)
INSTRUCTIONS = (
    "Official statistics of Azerbaijan from the State Statistical Committee (azstat.gov.az). "
    "Find a table with search_tables or list_topics, look at its dimensions, categories and "
    "periods with describe_table, then read rows with get_table_data and its period and category "
    "filters. Titles are English by default; use lang=az for Azerbaijani. A few tables give "
    "several values for the same period and categories and cannot be read reliably: they come "
    "back as status ambiguous with a link to the Committee's page. Cite the Committee as the "
    "source."
)
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
SUMMARY_CHARS = 300
DETAIL_CHARS = 3000
EXAMPLES = 25
Lang = Literal["en", "az"]
AMBIGUOUS = (
    "Several rows of this table share a period and categories, and the API does not say what sets "
    "them apart (it seems to leave out a dimension), so their values cannot be told apart. Read "
    "the table on the Committee's site instead."
)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _summary(entry: catalogue.Entry, chars: int) -> TableSummary:
    return TableSummary(
        table_id=entry.table_id,
        name=entry.name,
        description=_clip(entry.description, chars),
        topic_id=entry.topic_id,
        topic=entry.topic,
        url=TABLE_URL.format(table_id=entry.table_id),
    )


def _unique(names: tuple[str, ...]) -> list[str]:
    seen: dict[str, int] = {}
    unique = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        unique.append(name if seen[name] == 1 else f"{name} ({seen[name]})")
    return unique


def create_server(client: AzstatClient | None = None) -> FastMCP:
    """Build the server. Tests pass a client wired to a fake transport."""
    azstat = client or AzstatClient.from_env()
    mcp = FastMCP(name="azerbaijan-mcp-azstat", instructions=INSTRUCTIONS)

    async def guard(awaitable):
        try:
            return await awaitable
        except AzstatError as exc:
            raise ToolError(str(exc)) from exc

    def table_id_of(value: str) -> str:
        table_id = value.strip().upper()
        if not TABLE_ID.fullmatch(table_id):
            raise ToolError(
                f"{value!r} is not a table id such as DT_AA_001. Find ids with search_tables."
            )
        return table_id

    @mcp.tool(annotations=READ_ONLY)
    async def list_topics(
        lang: Annotated[Lang, Field(description="Language of the topic names.")] = "en",
    ) -> TopicList:
        """The Committee's statistical topics (demography, labour market, education and so on)."""
        entries = await guard(azstat.catalogue(lang))
        return TopicList(
            topics=[
                Topic(id=t.id, name=t.name, tables=t.tables) for t in catalogue.topics(entries)
            ],
            source=SOURCE_URL,
            attribution=ATTRIBUTION,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def search_tables(
        query: Annotated[
            str | None,
            Field(description="Words to find in a table's title or description; all must appear."),
        ] = None,
        topic: Annotated[
            str | None, Field(description="A topic id or part of a topic name, from list_topics.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=50, description="Tables to return.")] = 10,
        offset: Annotated[int, Field(ge=0, description="Tables to skip, for paging.")] = 0,
        lang: Annotated[
            Lang, Field(description="Language of titles and of the words searched.")
        ] = "en",
    ) -> TableSearch:
        """Search the Committee's statistical tables (about 1,800).

        Titles with the query words rank first. Use describe_table on a result to see what it
        holds. Without a query, the tables of the topic are listed.
        """
        entries = await guard(azstat.catalogue(lang))
        topic_ids = None
        if topic and topic.strip():
            topic_ids = catalogue.resolve_topics(entries, topic)
            if not topic_ids:
                raise ToolError(f"No topic matches {topic!r}. Use list_topics.")
        found = catalogue.search(entries, query or "", topic_ids)
        notes = []
        if not found:
            language, other = ("English", "az") if lang == "en" else ("Azerbaijani", "en")
            notes.append(f"Nothing matched in {language}. Try other words, or lang={other}.")
        return TableSearch(
            count=len(found),
            offset=offset,
            limit=limit,
            results=[_summary(entry, SUMMARY_CHARS) for entry in found[offset : offset + limit]],
            notes=notes,
            source=SOURCE_URL,
            attribution=ATTRIBUTION,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def describe_table(
        table_id: Annotated[
            str, Field(description="A table id from search_tables, such as DT_AA_001.")
        ],
        category_query: Annotated[
            str | None,
            Field(
                description="Words to look for in category names, to find the exact ones to filter."
            ),
        ] = None,
        lang: Annotated[Lang, Field(description="Language of names and categories.")] = "en",
    ) -> TableDescription:
        """What a table holds: its description, periods, units and each dimension's categories.

        Reads the whole table once (cached), so a big table takes a moment. Use the category
        names it shows in the where filter of get_table_data.
        """
        wanted = table_id_of(table_id)
        entries = await guard(azstat.catalogue(lang))
        entry = next((item for item in entries if item.table_id == wanted), None)
        if entry is None:
            raise ToolError(f"The catalogue has no table {wanted}. Find ids with search_tables.")
        summary = _summary(entry, DETAIL_CHARS)
        base = {"table": summary, "source": summary.url, "attribution": ATTRIBUTION}
        empty = {"rows": None, "periods": None, "first_period": None, "last_period": None}
        try:
            table = await azstat.table(wanted, lang)
        except TableTooLarge as exc:
            reason = f"{exc} Read the table on the Committee's site instead."
            return TableDescription(
                status="too_large",
                reason=reason,
                period_types=[],
                units=[],
                dimensions=[],
                notes=[],
                **empty,
                **base,
            )
        except AzstatError as exc:
            raise ToolError(str(exc)) from exc
        view = tables.overview(table, category_query, EXAMPLES)
        notes = []
        if (
            category_query
            and category_query.strip()
            and not any(d.matching for d in view.dimensions)
        ):
            notes.append(f"No category matches {category_query!r}.")
        return TableDescription(
            status="ambiguous" if table.ambiguous else "ok",
            reason=AMBIGUOUS if table.ambiguous else None,
            rows=view.rows,
            periods=view.periods,
            first_period=view.first_period,
            last_period=view.last_period,
            period_types=list(view.period_types),
            units=list(view.units),
            dimensions=[
                DimensionInfo(
                    name=d.name,
                    categories=d.categories,
                    matching=d.matching,
                    examples=list(d.examples),
                )
                for d in view.dimensions
            ],
            notes=notes,
            **base,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_table_data(
        table_id: Annotated[
            str, Field(description="A table id from search_tables, such as DT_AA_001.")
        ],
        period_from: Annotated[
            str | int | None,
            Field(
                description="First period to include: a year such as 2015, or 2025-03 for a month."
            ),
        ] = None,
        period_to: Annotated[
            str | int | None, Field(description="Last period to include, written like period_from.")
        ] = None,
        where: Annotated[
            dict[str, str | int | float] | None,
            Field(
                description="Category filters, for example "
                '{"Indicator": "Total population"}. A key is a dimension name or its number '
                "(1, 2, ...); a value is words that must appear in the category name. Every "
                "filter must match."
            ),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=500, description="Rows to return.")] = 50,
        offset: Annotated[int, Field(ge=0, description="Rows to skip, for paging.")] = 0,
        lang: Annotated[Lang, Field(description="Language of names and categories.")] = "en",
    ) -> TableData:
        """Rows of one statistical table in long format, filtered by period and category.

        `columns` names the cells of each row: the period, one column per dimension, the value,
        and symbol and unit when the rows have them. A null value with a symbol means the
        Committee published the symbol instead of a number. Use describe_table first to see the
        dimensions and the exact category names.
        """
        wanted = table_id_of(table_id)
        url = TABLE_URL.format(table_id=wanted)
        head = {"table_id": wanted, "url": url, "source": url, "attribution": ATTRIBUTION}

        def refusal(status: Status, name: str | None, reason: str) -> TableData:
            return TableData(
                status=status,
                reason=reason,
                name=name,
                columns=[],
                rows=[],
                total_rows=0,
                offset=offset,
                next_offset=None,
                notes=[],
                **head,
            )

        try:
            table = await azstat.table(wanted, lang)
        except TableTooLarge as exc:
            return refusal(
                "too_large", None, f"{exc} Read the table on the Committee's site instead."
            )
        except AzstatError as exc:
            raise ToolError(str(exc)) from exc
        if table.ambiguous:
            return refusal("ambiguous", table.name, AMBIGUOUS)
        try:
            chosen = tables.select(table, period_from=period_from, period_to=period_to, where=where)
        except tables.UnknownDimension as exc:
            raise ToolError(str(exc)) from exc
        page = chosen[offset : offset + limit]
        with_symbol = any(row.symbol for row in page)
        with_unit = any(row.unit for row in page)
        columns = ["period", *_unique(table.dimensions), "value"]
        columns += (["symbol"] if with_symbol else []) + (["unit"] if with_unit else [])
        rows = []
        for row in page:
            cells = [row.period, *row.categories, row.value]
            cells += ([row.symbol] if with_symbol else []) + ([row.unit] if with_unit else [])
            rows.append(cells)
        notes = []
        if not chosen:
            notes.append(
                "No rows matched. Check the periods and the category words with describe_table."
            )
        if with_symbol:
            notes.append("A null value with a symbol is published as that symbol; none is guessed.")
        end = offset + len(page)
        next_offset = end if end < len(chosen) else None
        if next_offset is not None:
            notes.append(f"{len(chosen) - end} more rows: call again with offset={next_offset}.")
        return TableData(
            status="ok",
            reason=None,
            name=table.name,
            columns=columns,
            rows=rows,
            total_rows=len(chosen),
            offset=offset,
            next_offset=next_offset,
            notes=notes,
            **head,
        )

    return mcp


mcp = create_server()


def main() -> None:
    """Console entry point: serve over stdio."""
    mcp.run(show_banner=False)
