import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from azerbaijan_mcp_dict.server import create_server
from azerbaijan_mcp_dict.store import Store

pytestmark = pytest.mark.anyio

TOOLS = {"define", "search", "browse", "read_entry"}


@pytest.fixture
def server(store):
    return create_server(store)


async def call(server, tool, arguments):
    async with Client(server) as mcp:
        return (await mcp.call_tool(tool, arguments)).structured_content


async def test_four_read_only_local_tools_are_listed(server):
    async with Client(server) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(tools) == TOOLS
    for tool in tools.values():
        assert tool.description
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.idempotent_hint is True
        assert tool.annotations.open_world_hint is False


async def test_define_answers_with_the_entry_its_citation_and_the_source(server, title):
    out = await call(server, "define", {"word": "kitab"})
    assert out["match"] == "exact"
    (entry,) = out["entries"]
    assert (entry["headword"], entry["origin"], entry["volume"]) == ("KİTAB", "ər.", 2)
    assert (entry["pdf_page"], entry["column"], entry["next_offset"]) == (7, 1, None)
    assert out["source"] == title
    assert "may contain errors" in out["attribution"]


async def test_define_follows_a_pointer_and_suggests_a_stem(server):
    out = await call(server, "define", {"word": "axça"})
    assert [(f["headword"], f["via"]) for f in out["followed"]] == [("AĞÇA", 5)]
    miss = await call(server, "define", {"word": "kitabları"})
    assert (miss["match"], miss["suggestions"]) == ("none", ["KİTAB"])


async def test_search_pages_and_ranks(server):
    out = await call(server, "search", {"query": "kitab", "limit": 2})
    assert (out["count"], out["next_offset"], out["results"][0]["headword"]) == (3, 2, "KİTAB")
    rest = await call(server, "search", {"query": "kitab", "limit": 2, "offset": 2})
    assert (len(rest["results"]), rest["next_offset"]) == (1, None)
    exact = await call(server, "search", {"query": "işıq", "exact": True})
    assert [hit["headword"] for hit in exact["results"]] == ["İŞIQ"]


async def test_browse_and_read_entry(server):
    out = await call(server, "browse", {"word": "kitab", "before": 1, "after": 1})
    assert [e["headword"] for e in out["entries"]] == ["İŞIQ", "KİTAB", "KİTABÇA"]
    assert (out["previous_id"], out["next_id"]) == (13, 17)
    onward = await call(server, "browse", {"entry_id": out["next_id"], "before": 0, "after": 0})
    assert [e["headword"] for e in onward["entries"]] == ["KİTABXANA"]
    first = await call(server, "read_entry", {"entry_id": 18, "max_chars": 500})
    assert first["headword"] == "OLMAQ"
    assert first["next_offset"]
    second = await call(
        server, "read_entry", {"entry_id": 18, "max_chars": 500, "offset": first["next_offset"]}
    )
    assert second["offset"] == first["next_offset"]


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        ("define", {"word": "..."}, "Give the word"),
        ("define", {"word": " "}, "Give the word"),
        ("search", {"query": "?"}, "at least one word"),
        ("browse", {}, "one of them"),
        ("browse", {"word": "su", "entry_id": 3}, "one of them"),
        ("browse", {"entry_id": 999}, "No entry has id 999"),
        ("read_entry", {"entry_id": 999}, "No entry has id 999"),
    ],
)
async def test_questions_that_cannot_be_answered_are_tool_errors(server, tool, arguments, message):
    with pytest.raises(ToolError, match=message):
        await call(server, tool, arguments)


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("define", {"word": ""}),
        ("define", {"word": "su", "max_chars": 100}),
        ("search", {"query": "su", "limit": 0}),
        ("search", {"query": "su", "offset": -1}),
        ("browse", {"word": "su", "before": 51}),
        ("read_entry", {"entry_id": 0}),
        ("read_entry", {"entry_id": 1, "max_chars": 60000}),
        # numbers SQLite cannot take are refused before they reach it
        ("search", {"query": "su", "offset": 2**63}),
        ("browse", {"entry_id": 2**63}),
        ("read_entry", {"entry_id": 2**63}),
        ("read_entry", {"entry_id": 1, "offset": 2**63}),
    ],
)
async def test_arguments_out_of_range_are_refused(server, tool, arguments):
    with pytest.raises(ToolError):
        await call(server, tool, arguments)


async def test_a_word_of_the_highest_code_point_is_just_not_found(server):
    out = await call(server, "define", {"word": "\U0010ffff"})
    assert out["match"] == "none"


async def test_a_server_whose_database_cannot_be_downloaded_says_how_to_go_on(tmp_path, site):
    server = create_server(Store(None, tmp_path, transport=site(httpx.Response(404)).transport))
    async with Client(server) as mcp:
        assert {tool.name for tool in await mcp.list_tools()} == TOOLS
    with pytest.raises(ToolError, match="DICT_DB"):
        await call(server, "define", {"word": "su"})
