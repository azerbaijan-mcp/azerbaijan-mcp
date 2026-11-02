"""FastMCP server for e-qanun.az, the legal acts base of the Ministry of Justice."""

import asyncio
import datetime as dt
import re
from collections.abc import Iterable
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from . import acts
from .client import EqanunClient, SearchField, StatusFilter
from .errors import EqanunError, NotFound, TooLarge
from .listing import ActSummary, resolve_types
from .models import (
    ActDetails,
    ActInfo,
    ActReference,
    ActSearch,
    AmendmentNote,
    ArticleText,
    Publication,
    TextMatch,
    TextSearch,
)

SOURCE_URL = "https://e-qanun.az"
ACT_URL = "https://e-qanun.az/framework/{act_id}"
ATTRIBUTION = (
    "Source: e-qanun.az, the legal acts base of the Ministry of Justice of Azerbaijan. This is an "
    "unofficial copy read on the date given; the official source is the State Register of Legal "
    "Acts."
)
INSTRUCTIONS = (
    "Legal acts of Azerbaijan from e-qanun.az, the Ministry of Justice's legal acts base. Find an "
    "act with search_acts (by title, or with field=text by what its text says), see its details "
    "and read its text with get_act, read one article with its amendment notes with get_article, "
    "and look for words inside a long act with find_in_act. Only acts in force are searched unless "
    "status says otherwise; an act that is repealed is flagged and must not be presented as "
    "current law. Texts are unofficial copies, read from the site on the date each answer gives; "
    "cite the act with its e-qanun.az page and name the State Register of Legal Acts as the "
    "official source. This server runs on your computer and reads the site politely, one request "
    "a second, so a long act takes a moment the first time."
)
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
NOTE_MARKER = re.compile(r"\[(\d+)\]")
KIND_HINT = (
    "Use words from its name, such as qanun, məcəllə, fərman, sərəncam, qərar or a ministry."
)
SHOWN_KINDS = 8


def _stamp(moment: dt.datetime) -> str:
    return moment.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _info(summary: ActSummary) -> ActInfo:
    return ActInfo(
        id=summary.id,
        title=summary.title,
        type=summary.type,
        number=summary.citation,
        status=summary.status,
        status_text=summary.status_text,
        accepted=summary.accept_date,
        effective=summary.effect_date,
        register_code=summary.register_code,
        url=ACT_URL.format(act_id=summary.id),
    )


def _status_notes(info: ActInfo) -> list[str]:
    if info.status == "repealed":
        return [
            f"This act is repealed (the site says: {info.status_text}). Its text is a record of "
            "what once applied; do not present it as current law."
        ]
    if info.status == "unknown":
        said = f"as {info.status_text!r}" if info.status_text else "not at all"
        return [f"The site gives this act's status {said}; check it on {info.url}."]
    return []


def _amendments(text: str, notes: Iterable[tuple[int, str]]) -> list[AmendmentNote]:
    """The notes whose markers are in the text."""
    used = {int(number) for number in NOTE_MARKER.findall(text)}
    return [AmendmentNote(marker=number, text=note) for number, note in notes if number in used]


def _references(links: Iterable[acts.Reference]) -> list[ActReference]:
    return [
        ActReference(
            label=link.label,
            act_id=link.act_id,
            title=link.title,
            url=ACT_URL.format(act_id=link.act_id),
        )
        for link in links
    ]


def _more(rest: int, offset: int | None) -> list[str]:
    if offset is None:
        return []
    return [f"{rest:,} more characters: call again with offset={offset}."]


def create_server(client: EqanunClient | None = None) -> FastMCP:
    """Build the server. Tests pass a client wired to a fake transport."""
    eqanun = client or EqanunClient.from_env()
    mcp = FastMCP(name="azerbaijan-mcp-eqanun", instructions=INSTRUCTIONS)

    async def guard(awaitable):
        try:
            return await awaitable
        except EqanunError as exc:
            raise ToolError(str(exc)) from exc

    async def read_act(act_id: int):
        """The act's details, its parsed file and the time the file was read."""
        meta = (await guard(eqanun.framework(act_id))).value
        info = _info(meta.summary)
        try:
            fetched = await eqanun.act(act_id)
        except TooLarge as exc:
            raise ToolError(f"{exc} Read the act on e-qanun.az instead: {info.url}") from exc
        except EqanunError as exc:
            raise ToolError(str(exc)) from exc
        return info, fetched.value, _stamp(fetched.fetched_at)

    @mcp.tool(annotations=READ_ONLY)
    async def search_acts(
        query: Annotated[
            str | None,
            Field(
                description="Words to find in the title (in the text with field=text); all must "
                "appear. Leave out to list the newest acts."
            ),
        ] = None,
        field: Annotated[
            SearchField,
            Field(
                description="title (default), or text to find acts whose full text has the words."
            ),
        ] = "title",
        type: Annotated[
            str | None,
            Field(
                description="Kind of act, as words from its name: qanun, məcəllə, fərman, "
                "sərəncam, qərar, Nazirlər Kabineti, or a ministry's name."
            ),
        ] = None,
        status: Annotated[
            StatusFilter,
            Field(description="in_force (default), repealed or all."),
        ] = "in_force",
        exact: Annotated[bool, Field(description="Find the words together, as a phrase.")] = False,
        limit: Annotated[int, Field(ge=1, le=50, description="Acts to return.")] = 10,
        offset: Annotated[int, Field(ge=0, description="Acts to skip, for paging.")] = 0,
    ) -> ActSearch:
        """Search the legal acts on e-qanun.az, newest adoption date first.

        Laws, codes, decrees, orders and decisions of the President, the Cabinet, ministries and
        courts. Only acts in force are listed unless status says otherwise. Read a result with
        get_act, and use field=text to find acts by what their text says.
        """
        words = (query or "").strip()
        if field == "text" and not words:
            raise ToolError("Give the words to look for in the text.")
        notes = []
        type_ids: tuple[int, ...] = ()
        if type and type.strip():
            nodes = (await guard(eqanun.types())).value
            kinds = resolve_types(nodes, type)
            if not kinds:
                raise ToolError(f"No kind of act matches {type!r}. {KIND_HINT}")
            type_ids = tuple(kind.id for kind in kinds)
            names = ", ".join(kind.name for kind in kinds[:SHOWN_KINDS])
            notes.append(f"Kinds searched: {names}{'…' if len(kinds) > SHOWN_KINDS else ''}.")
        found = await guard(
            eqanun.search(
                words,
                field=field,
                status=status,
                type_ids=type_ids,
                exact=exact,
                start=offset,
                length=limit,
            )
        )
        total, rows = found.value
        end = offset + len(rows)
        if not total:
            notes.append(
                "Nothing matched. Try fewer words, status=all (repealed acts are left out by "
                "default) or field=text."
            )
        return ActSearch(
            count=total,
            offset=offset,
            limit=limit,
            next_offset=end if end < total else None,
            results=[_info(row) for row in rows],
            notes=notes,
            fetched_at=_stamp(found.fetched_at),
            source=SOURCE_URL,
            attribution=ATTRIBUTION,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_act(
        act_id: Annotated[int, Field(ge=1, description="An act id from search_acts.")],
        offset: Annotated[
            int,
            Field(
                ge=0,
                description="Character to start the text at; next_offset of an answer reads on.",
            ),
        ] = 0,
        max_chars: Annotated[
            int, Field(ge=500, le=50000, description="Longest piece of text to return.")
        ] = 6000,
    ) -> ActDetails:
        """An act's details and its text from `offset`.

        Gives the title, kind, status, dates, where it was published, the dates of its editions
        and, for an act divided into articles, how many there are. The text carries [n] markers
        of amendment notes, which come with it, and the acts it links to are listed in
        `references`. Use get_article for one article of a code or law.
        """
        framework = await guard(eqanun.framework(act_id))
        meta = framework.value
        versions = (await guard(eqanun.versions(act_id))).value
        info = _info(meta.summary)
        notes = _status_notes(info)
        head = {
            "act": info,
            "register_date": meta.register_date,
            "class_codes": list(meta.class_codes),
            "publications": [
                Publication(
                    source=p.source, details=[f"{name}: {value}" for name, value in p.details]
                )
                for p in meta.publications
            ],
            "edition_dates": sorted(
                {v.effective_date for v in versions if v.effective_date}, reverse=True
            ),
            "source": info.url,
            "attribution": ATTRIBUTION,
        }
        try:
            fetched = await eqanun.act(act_id)
        except TooLarge as exc:
            return ActDetails(
                status="too_large",
                reason=f"{exc} Read the act on e-qanun.az instead.",
                structure=None,
                articles=None,
                first_article=None,
                last_article=None,
                total_chars=None,
                offset=offset,
                next_offset=None,
                text=None,
                amendment_notes=[],
                references=[],
                notes=notes,
                fetched_at=_stamp(framework.fetched_at),
                **head,
            )
        except EqanunError as exc:
            raise ToolError(str(exc)) from exc
        parsed = fetched.value
        piece, next_offset = acts.window(parsed.text, offset, max_chars)
        if parsed.articles:
            notes.append(
                "This act is divided into articles: get_article reads one, and find_in_act "
                "looks for words in it."
            )
        notes += _more(len(parsed.text) - (next_offset or 0), next_offset)
        return ActDetails(
            status="ok",
            reason=None,
            structure="articles" if parsed.articles else "paragraphs",
            articles=len(parsed.articles) or None,
            first_article=parsed.articles[0].number if parsed.articles else None,
            last_article=parsed.articles[-1].number if parsed.articles else None,
            total_chars=len(parsed.text),
            offset=offset,
            next_offset=next_offset,
            text=piece,
            amendment_notes=_amendments(piece, sorted(parsed.notes.items())),
            references=_references(acts.references_between(parsed, offset, offset + len(piece))),
            notes=notes,
            fetched_at=_stamp(fetched.fetched_at),
            **head,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_article(
        act_id: Annotated[int, Field(ge=1, description="An act id from search_acts.")],
        article: Annotated[
            str | int,
            Field(
                description="Article number such as 105, or 105-1 for an article added later. "
                "'Maddə 105' is accepted, and 105.1 reads article 105."
            ),
        ],
        offset: Annotated[
            int, Field(ge=0, description="Character to start at, for a long article.")
        ] = 0,
        max_chars: Annotated[
            int, Field(ge=500, le=50000, description="Longest piece of text to return.")
        ] = 12000,
    ) -> ArticleText:
        """One article of a code or law, with the amendment notes that belong to it.

        An amendment note says which later law added, changed or repealed the passage; its [n]
        marker is in the text. Labels such as KMQ23 mark a court decision on the passage; the acts
        the article links to are listed in `references`, with their ids for get_act. The answer
        names the neighbouring articles. Works only for acts divided into articles; read others
        with get_act.
        """
        try:
            number, remark = acts.normalize_article(article)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        info, parsed, stamp = await read_act(act_id)
        if not parsed.articles:
            raise ToolError(
                "This act is not divided into articles. Read it with get_act, or look for words "
                "in it with find_in_act."
            )
        try:
            view = acts.article_view(parsed, number)
        except NotFound as exc:
            first, last = parsed.articles[0].number, parsed.articles[-1].number
            raise ToolError(
                f"{exc} Its articles run from {first} to {last} ({len(parsed.articles):,} in "
                "all); find_in_act can look for words."
            ) from exc
        piece, next_offset = acts.window(view.text, offset, max_chars)
        notes = _status_notes(info) + ([remark] if remark else [])
        notes += _more(len(view.text) - (next_offset or 0), next_offset)
        return ArticleText(
            act=info,
            article=number,
            heading=view.heading,
            text=piece,
            total_chars=len(view.text),
            offset=offset,
            next_offset=next_offset,
            amendment_notes=_amendments(f"{view.heading}\n{piece}", view.notes),
            references=_references(view.references),
            previous_article=view.previous,
            next_article=view.next,
            notes=notes,
            fetched_at=stamp,
            source=info.url,
            attribution=ATTRIBUTION,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def find_in_act(
        act_id: Annotated[int, Field(ge=1, description="An act id from search_acts.")],
        query: Annotated[
            str,
            Field(
                min_length=1,
                description="Words to find; all must appear in the same article. Accents may be "
                "left out: mehdudlasdirma finds məhdudlaşdırma.",
            ),
        ],
        limit: Annotated[int, Field(ge=1, le=50, description="Results to return.")] = 10,
        offset: Annotated[int, Field(ge=0, description="Results to skip, for paging.")] = 0,
    ) -> TextSearch:
        """Find the articles of one act that contain all the words, the most occurrences first.

        Use it to locate a topic in a long code, then read the article with get_article. In an act
        without articles each result is a paragraph; `position` is the offset to give get_act.
        """
        words = query.strip()
        if not words:
            raise ToolError("Give the words to look for.")
        info, parsed, stamp = await read_act(act_id)
        total, matches = await asyncio.to_thread(acts.search_act, parsed, words, limit, offset)
        end = offset + len(matches)
        notes = _status_notes(info)
        if not total:
            notes.append("Nothing matched. Try fewer or other words; accents may be left out.")
        if not parsed.articles:
            notes.append("This act has no articles, so each result is a paragraph.")
        return TextSearch(
            act=info,
            query=words,
            unit="article" if parsed.articles else "paragraph",
            count=total,
            offset=offset,
            limit=limit,
            next_offset=end if end < total else None,
            results=[
                TextMatch(
                    article=m.article,
                    heading=m.heading,
                    matches=m.hits,
                    snippet=m.snippet,
                    position=m.position,
                )
                for m in matches
            ],
            notes=notes,
            fetched_at=stamp,
            source=info.url,
            attribution=ATTRIBUTION,
        )

    return mcp


mcp = create_server()


def main() -> None:
    """Console entry point: serve over stdio."""
    mcp.run(show_banner=False)
