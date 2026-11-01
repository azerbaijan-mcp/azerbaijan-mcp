import json

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from azerbaijan_mcp_opendata.server import create_server

pytestmark = pytest.mark.anyio

TOOLS = {
    "search_datasets",
    "get_dataset",
    "list_organizations",
    "list_groups",
    "list_licenses",
    "preview_resource",
}


@pytest.fixture
def server(client):
    return create_server(client)


async def call(server, tool, arguments=None):
    async with Client(server) as mcp:
        return (await mcp.call_tool(tool, arguments or {})).structured_content


def answer(portal, action, body):
    """Make the portal answer one CKAN action with `body`; everything else stays as it was."""

    def override(request):
        if request.url.path.endswith(f"/{action}"):
            return httpx.Response(200, json=body)

    portal.override = override


def serve(portal, host, response):
    """Make the portal answer every request to `host` with `response()`."""

    def override(request):
        if request.url.host == host:
            return response()

    portal.override = override


async def test_six_read_only_tools_are_listed(server):
    async with Client(server) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(tools) == TOOLS
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())
    assert all(tool.description for tool in tools.values())


async def test_search_without_filters_lists_the_newest_datasets(server, portal, ids):
    out = await call(server, "search_datasets")
    assert (out["count"], out["offset"], out["limit"]) == (130, 0, 10)
    first = out["results"][0]
    assert first["name"] == ids.name
    assert first["organization"] == {
        "name": "dsk",
        "title": "Azərbaycan Respublikasının Dövlət Statistika Komitəsi",
    }
    assert first["license"]["known"] is True
    assert first["formats"] == ["CSV", "JSON"]
    assert out["notes"] == []
    assert "opendata.az" in out["attribution"]
    assert dict(portal.calls[-1].params) == {
        "rows": "10",
        "start": "0",
        "sort": "metadata_modified desc",
    }


async def test_filters_are_sent_as_a_solr_filter_query(server, portal):
    await call(
        server,
        "search_datasets",
        {
            "query": " population ",
            "organization": "dsk",
            "group": "economics",
            "license": "cc-zero",
            "format": "CSV",
            "limit": 5,
            "offset": 10,
        },
    )
    assert dict(portal.calls[-1].params) == {
        "q": "population",
        "fq": 'organization:"dsk" groups:"economics" license_id:"cc-zero" res_format:"CSV"',
        "rows": "5",
        "start": "10",
        "sort": "score desc, metadata_modified desc",
    }


async def test_empty_filters_and_text_are_ignored(server, portal):
    await call(server, "search_datasets", {"query": "  ", "organization": " ", "format": ""})
    assert set(dict(portal.calls[-1].params)) == {"rows", "start", "sort"}


@pytest.mark.parametrize(
    "arguments",
    [
        {"organization": 'dsk" OR license_id:"x'},
        {"group": "two words"},
        {"license": "cc-zero)"},
        {"format": "*:*"},
        {"organization": "x" * 101},
    ],
)
async def test_a_filter_that_is_not_a_short_id_is_refused(server, portal, arguments):
    with pytest.raises(ToolError, match="must be a short id"):
        await call(server, "search_datasets", arguments)
    assert portal.calls == []


@pytest.mark.parametrize("arguments", [{"limit": 0}, {"limit": 51}, {"offset": -1}, {"lang": "fr"}])
async def test_out_of_range_arguments_are_refused(server, arguments):
    with pytest.raises(ToolError):
        await call(server, "search_datasets", arguments)


async def test_titles_follow_the_language(server):
    out = await call(server, "search_datasets", {"lang": "az"})
    assert out["results"][0]["title"].startswith("Əhalinin gəlirləri")


async def test_search_says_so_when_nothing_matches(server, portal):
    answer(portal, "package_search", {"success": True, "result": {"count": 0, "results": []}})
    out = await call(server, "search_datasets", {"query": "zzz"})
    assert out["results"] == []
    assert out["notes"] == ["Nothing matched. Try fewer filters or other words."]


async def test_search_warns_about_datasets_without_a_licence(server, portal, read):
    body = json.loads(read("search_population.json"))
    body["result"]["results"][0]["license_id"] = "notspecified"
    answer(portal, "package_search", body)
    out = await call(server, "search_datasets")
    assert out["results"][0]["license"]["known"] is False
    assert any("state no licence" in note for note in out["notes"])


async def test_get_dataset_by_slug_or_id_lists_its_files(server, ids):
    by_slug = await call(server, "get_dataset", {"dataset_id": ids.name})
    by_id = await call(server, "get_dataset", {"dataset_id": f"  {ids.dataset} "})
    assert by_slug == by_id
    assert by_slug["source"] == f"https://opendata.az/en/dataset/{ids.name}"
    assert by_slug["tags"] == ["national_accounts"]
    files = {item["id"]: item for item in by_slug["resources"]}
    assert set(files) == {ids.portal_csv, ids.azstat_csv, ids.azstat_json}
    assert all(item["previewable"] for item in files.values())
    assert "opendata.az" in by_slug["attribution"]


async def test_get_dataset_leaves_out_individuals(server, portal, ids):
    portal.show["result"].update(
        author="Jane Doe",
        author_email="jane@example.org",
        maintainer="John Roe",
        maintainer_email="john@example.org",
    )
    out = await call(server, "get_dataset", {"dataset_id": ids.name})
    text = json.dumps(out, ensure_ascii=False)
    for value in ("Jane Doe", "jane@example.org", "John Roe", "john@example.org"):
        assert value not in text


async def test_an_unknown_dataset_is_a_tool_error(server):
    with pytest.raises(ToolError, match="no dataset 'nope'"):
        await call(server, "get_dataset", {"dataset_id": "nope"})


@pytest.mark.parametrize(
    ("tool", "count", "first", "filter_name"),
    [
        ("list_organizations", 53, "dsk", "organization"),
        ("list_groups", 12, "economics", "group"),
        ("list_licenses", 10, "cc-zero", "license"),
    ],
)
async def test_the_list_tools_return_filter_values_largest_first(
    server, tool, count, first, filter_name
):
    out = await call(server, tool)
    assert len(out["items"]) == count
    assert out["items"][0]["name"] == first
    assert out["notes"] == [f"Pass a name as the {filter_name} filter of search_datasets."]


async def test_the_three_list_tools_share_one_request(server, portal):
    for tool in ("list_organizations", "list_groups", "list_licenses"):
        await call(server, tool)
    assert len(portal.calls) == 1


async def test_preview_a_csv_hosted_by_the_portal(server, portal, ids, read):
    out = await call(
        server,
        "preview_resource",
        {"dataset_id": ids.name, "resource_id": ids.portal_csv, "rows": 3},
    )
    assert out["status"] == "ok"
    assert (out["format"], out["delimiter"], out["encoding"]) == ("CSV", ";", "utf-8")
    assert out["rows"][0][0] == "Example table title"
    assert (len(out["rows"]), out["total_rows"], out["truncated"]) == (3, 5, True)
    assert out["size_bytes"] == len(read("portal_style.csv"))
    assert out["url"] == portal.resource(ids.portal_csv)["url"]
    assert out["license"]["id"] == "cc-zero"
    assert out["source"] == f"https://opendata.az/en/dataset/{ids.name}"
    assert "opendata.az" in out["attribution"]
    assert out["records"] is None


async def test_preview_a_csv_and_a_json_file_from_azstat(server, ids):
    csv_out = await call(
        server, "preview_resource", {"dataset_id": ids.name, "resource_id": ids.azstat_csv}
    )
    assert (csv_out["status"], csv_out["delimiter"], csv_out["total_rows"]) == ("ok", ",", 12)
    assert csv_out["rows"][0][0] == "TIME_PERIOD"
    json_out = await call(
        server,
        "preview_resource",
        {"dataset_id": ids.name, "resource_id": f" {ids.azstat_json} ", "rows": 2},
    )
    assert (json_out["status"], json_out["table_key"]) == ("ok", "data")
    assert (len(json_out["records"]), json_out["total_records"], json_out["truncated"]) == (
        2,
        6,
        True,
    )
    assert json_out["meta"]["count"] == 6
    assert json_out["rows"] is None


async def test_a_format_that_is_not_previewed_returns_the_link(server, portal, ids):
    portal.resource(ids.azstat_csv)["format"] = "XLSX"
    out = await call(
        server, "preview_resource", {"dataset_id": ids.name, "resource_id": ids.azstat_csv}
    )
    assert out["status"] == "unsupported_format"
    assert "XLSX files are not previewed" in out["reason"]
    assert out["url"].startswith("https://www.azstat.gov.az/")
    assert [u.host for u in portal.calls] == ["admin.opendata.az"]


async def test_a_file_on_another_host_returns_the_link_and_is_never_fetched(server, portal, ids):
    portal.resource(ids.azstat_csv)["url"] = "https://example.com/data.csv"
    out = await call(
        server, "preview_resource", {"dataset_id": ids.name, "resource_id": ids.azstat_csv}
    )
    assert (out["status"], out["url"]) == ("link_only", "https://example.com/data.csv")
    assert "outside the allowed hosts" in out["reason"]
    assert [u.host for u in portal.calls] == ["admin.opendata.az"]


async def test_a_redirect_to_another_host_returns_the_link(server, portal, ids):
    def override(request):
        if "/download/" in request.url.path:
            return httpx.Response(302, headers={"location": "https://internal.example/x.csv"})

    portal.override = override
    out = await call(
        server, "preview_resource", {"dataset_id": ids.name, "resource_id": ids.portal_csv}
    )
    assert out["status"] == "link_only"
    assert "redirects away from" in out["reason"]
    assert all(u.host != "internal.example" for u in portal.calls)


async def test_a_file_over_five_megabytes_returns_the_link(server, portal, ids):
    serve(
        portal,
        "data-storage.opendata.az",
        lambda: httpx.Response(200, headers={"content-length": str(6 * 1024 * 1024)}, content=b"x"),
    )
    out = await call(
        server, "preview_resource", {"dataset_id": ids.name, "resource_id": ids.portal_csv}
    )
    assert out["status"] == "too_large"
    assert "preview limit is 5 MB" in out["reason"]
    assert out["url"] == portal.resource(ids.portal_csv)["url"]


async def test_an_unknown_file_lists_the_real_ones(server, ids):
    with pytest.raises(ToolError, match=rf"no file 'nope'.*{ids.portal_csv}.*{ids.azstat_json}"):
        await call(server, "preview_resource", {"dataset_id": ids.name, "resource_id": "nope"})


async def test_a_file_that_is_not_the_json_it_claims_to_be_is_a_tool_error(server, portal, ids):
    serve(portal, "www.azstat.gov.az", lambda: httpx.Response(200, text="<html>maintenance</html>"))
    with pytest.raises(ToolError, match="not valid JSON"):
        await call(
            server, "preview_resource", {"dataset_id": ids.name, "resource_id": ids.azstat_json}
        )


async def test_a_web_page_in_place_of_the_file_is_a_tool_error(server, portal, ids):
    page = httpx.Response(
        200, text="<html>error</html>", headers={"content-type": "text/html; charset=utf-8"}
    )
    serve(portal, "www.azstat.gov.az", lambda: page)
    with pytest.raises(ToolError, match="web page instead of the file"):
        await call(
            server, "preview_resource", {"dataset_id": ids.name, "resource_id": ids.azstat_csv}
        )


async def test_a_file_that_is_gone_is_a_tool_error(server, portal, ids):
    serve(portal, "www.azstat.gov.az", lambda: httpx.Response(404))
    with pytest.raises(ToolError, match="gone"):
        await call(
            server, "preview_resource", {"dataset_id": ids.name, "resource_id": ids.azstat_csv}
        )


@pytest.mark.parametrize("rows", [0, 201])
async def test_the_row_count_is_bounded(server, ids, rows):
    with pytest.raises(ToolError):
        await call(
            server,
            "preview_resource",
            {"dataset_id": ids.name, "resource_id": ids.azstat_csv, "rows": rows},
        )
