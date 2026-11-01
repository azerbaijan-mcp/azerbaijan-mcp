"""FastMCP server for opendata.az, the official open data portal of Azerbaijan."""

import re
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from . import datasets, preview
from .client import OpenDataClient, PortalError, ResourceRefused
from .models import DatasetDetail, FacetList, ResourcePreview, SearchResult

SOURCE_URL = "https://opendata.az"
ATTRIBUTION = (
    "Source: IDDA Open Data Portal (opendata.az). Every dataset keeps its own licence and "
    "publisher; check license.known before reusing data."
)
INSTRUCTIONS = (
    "Search and read the official open data portal of Azerbaijan (opendata.az, run by IDDA). "
    "Start with search_datasets and narrow it with ids from list_organizations, list_groups and "
    "list_licenses. get_dataset shows a dataset's files; preview_resource looks inside a CSV or "
    "JSON file. Each dataset has its own licence. Say where the data comes from."
)
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
HELPERS = {
    "organization": "list_organizations",
    "group": "list_groups",
    "license": "list_licenses",
    "format": "a format name such as CSV or JSON",
}
Lang = Literal["en", "az", "ru"]


def _slug(value: str | None, what: str) -> str | None:
    """A filter value is a short id; anything else could change the meaning of the query."""
    if value is None or not value.strip():
        return None
    text = value.strip()
    if not SLUG.fullmatch(text):
        raise ToolError(f"The {what} filter must be a short id, taken from {HELPERS[what]}.")
    return text


def create_server(client: OpenDataClient | None = None) -> FastMCP:
    """Build the server. Tests pass a client wired to a fake transport."""
    portal = client or OpenDataClient.from_env()
    mcp = FastMCP(name="azerbaijan-mcp-opendata", instructions=INSTRUCTIONS)

    async def guard(awaitable):
        try:
            return await awaitable
        except PortalError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(annotations=READ_ONLY)
    async def search_datasets(
        query: Annotated[
            str | None, Field(description="Words to search for, in Azerbaijani or English.")
        ] = None,
        organization: Annotated[
            str | None, Field(description="Publisher id from list_organizations, for example dsk.")
        ] = None,
        group: Annotated[
            str | None, Field(description="Topic id from list_groups, for example economics.")
        ] = None,
        license: Annotated[
            str | None, Field(description="Licence id from list_licenses, for example cc-zero.")
        ] = None,
        format: Annotated[
            str | None,
            Field(
                description="Format as the portal spells it: CSV, JSON, GeoJSON, XLSX, XLS, XML."
            ),
        ] = None,
        limit: Annotated[int, Field(ge=1, le=50, description="Datasets to return.")] = 10,
        offset: Annotated[int, Field(ge=0, description="Datasets to skip, for paging.")] = 0,
        lang: Annotated[Lang, Field(description="Preferred language for titles.")] = "en",
    ) -> SearchResult:
        """Search the open datasets on opendata.az.

        Returns title, publisher, licence and file formats for each match; use get_dataset for the
        files. All filters are optional and combine with AND.
        """
        fq = []
        for field, value, what in (
            ("organization", organization, "organization"),
            ("groups", group, "group"),
            ("license_id", license, "license"),
            ("res_format", format, "format"),
        ):
            clean = _slug(value, what)
            if clean:
                fq.append(f'{field}:"{clean}"')
        text = (query or "").strip() or None
        sort = "score desc, metadata_modified desc" if text else "metadata_modified desc"
        result = await guard(portal.search(q=text, fq=fq, rows=limit, start=offset, sort=sort))
        found = [datasets.summarize(raw, lang) for raw in result["results"]]
        notes = []
        if not found:
            notes.append("Nothing matched. Try fewer filters or other words.")
        if any(not item.license.known for item in found):
            notes.append("Some datasets state no licence; check with the publisher before reuse.")
        return SearchResult(
            count=int(result["count"]),
            offset=offset,
            limit=limit,
            results=found,
            source=SOURCE_URL,
            attribution=ATTRIBUTION,
            notes=notes,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def get_dataset(
        dataset_id: Annotated[str, Field(description="A dataset id or its URL slug.")],
        lang: Annotated[Lang, Field(description="Preferred language for titles.")] = "en",
    ) -> DatasetDetail:
        """Read one dataset: description, publisher, licence, tags and its files.

        Names and e-mail addresses of individuals are not included. Use a file's id with
        preview_resource.
        """
        raw = await guard(portal.show(dataset_id.strip()))
        return datasets.detail(raw, lang, portal.host_allowed, ATTRIBUTION)

    async def facet_list(field: str, what: str) -> FacetList:
        result = await guard(portal.facets())
        return FacetList(
            items=datasets.facet_items(result, field),
            source=SOURCE_URL,
            attribution=ATTRIBUTION,
            notes=[f"Pass a name as the {what} filter of search_datasets."],
        )

    @mcp.tool(annotations=READ_ONLY)
    async def list_organizations() -> FacetList:
        """Publishers on the portal with their dataset counts, largest first."""
        return await facet_list("organization", "organization")

    @mcp.tool(annotations=READ_ONLY)
    async def list_groups() -> FacetList:
        """Topics (groups) on the portal with their dataset counts, largest first."""
        return await facet_list("groups", "group")

    @mcp.tool(annotations=READ_ONLY)
    async def list_licenses() -> FacetList:
        """Licences on the portal with dataset counts. `notspecified` means none is stated."""
        return await facet_list("license_id", "license")

    @mcp.tool(annotations=READ_ONLY)
    async def preview_resource(
        dataset_id: Annotated[str, Field(description="A dataset id or its URL slug.")],
        resource_id: Annotated[str, Field(description="A file id from get_dataset.")],
        rows: Annotated[int, Field(ge=1, le=200, description="Rows or records to return.")] = 20,
    ) -> ResourcePreview:
        """Look inside a CSV or JSON file of a dataset.

        Only https files on opendata.az and azstat.gov.az are fetched, up to 5 MB. For anything
        else the result has status link_only, unsupported_format or too_large and the file's own
        address. In a CSV the first row is often a title, not a header.
        """
        raw = await guard(portal.show(dataset_id.strip()))
        info = datasets.detail(raw, "en", portal.host_allowed, ATTRIBUTION)
        wanted = resource_id.strip()
        match = next((item for item in info.resources if item.id == wanted), None)
        if match is None:
            listing = "; ".join(
                f"{item.id} ({item.format or '?'}) {item.name}" for item in info.resources
            )
            raise ToolError(f"Dataset {info.name} has no file {wanted!r}. Its files: {listing}")
        base = {
            "dataset_id": info.id,
            "resource_id": match.id,
            "resource_name": match.name,
            "format": match.format,
            "url": match.url,
            "license": info.license,
            "source": info.url,
            "attribution": ATTRIBUTION,
        }
        if match.format not in datasets.PREVIEW_FORMATS:
            return ResourcePreview(status="unsupported_format", reason=match.preview_note, **base)
        if not portal.host_allowed(match.url):
            return ResourcePreview(status="link_only", reason=match.preview_note, **base)
        try:
            content, content_type = await portal.fetch_resource(match.url)
        except ResourceRefused as refused:
            return ResourcePreview(status=refused.status, reason=refused.reason, **base)
        except PortalError as exc:
            raise ToolError(str(exc)) from exc
        if content_type.lower().startswith("text/html"):
            raise ToolError("The file's host returned a web page instead of the file.")
        try:
            parsed = (
                preview.preview_csv(content, rows)
                if match.format == "CSV"
                else preview.preview_json(content, rows)
            )
        except preview.PreviewError as exc:
            raise ToolError(str(exc)) from exc
        return ResourcePreview(status="ok", size_bytes=len(content), **parsed, **base)

    return mcp


mcp = create_server()


def main() -> None:
    """Console entry point: serve over stdio."""
    mcp.run(show_banner=False)
