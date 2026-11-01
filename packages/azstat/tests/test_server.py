import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from azerbaijan_mcp_azstat.server import create_server

pytestmark = pytest.mark.anyio

TOOLS = {"list_topics", "search_tables", "describe_table", "get_table_data"}
TOO_BIG = 30 * 1024 * 1024


@pytest.fixture
def server(client):
    return create_server(client)


async def call(server, tool, arguments=None):
    async with Client(server) as mcp:
        return (await mcp.call_tool(tool, arguments or {})).structured_content


def too_big(portal):
    def override(request):
        if request.url.path.endswith("/data"):
            return httpx.Response(200, headers={"content-length": str(TOO_BIG)}, content=b"{}")

    portal.override = override


async def test_four_read_only_tools_are_listed(server):
    async with Client(server) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(tools) == TOOLS
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())
    assert all(tool.description for tool in tools.values())


async def test_topics_are_named_in_the_requested_language(server):
    english = await call(server, "list_topics")
    names = {t["id"]: t["name"] for t in english["topics"]}
    assert names["994_001"] == "Demographic indicators"
    assert names["994_002"] == "Labour market"
    assert sum(t["tables"] for t in english["topics"]) == 39
    azerbaijani = await call(server, "list_topics", {"lang": "az"})
    assert {t["id"]: t["name"] for t in azerbaijani["topics"]}[
        "994_001"
    ] == "Demoqrafik göstəricilər"
    assert "State Statistical Committee" in english["attribution"]


async def test_search_finds_tables_by_words_and_links_to_their_pages(server):
    out = await call(server, "search_tables", {"query": "population"})
    first = out["results"][0]
    assert first["table_id"] == "DT_AA_001"
    assert (first["topic_id"], first["topic"]) == ("994_001", "Demographic indicators")
    assert (
        first["url"] == "https://www.azstat.gov.az/statHtml/statHtml.do?orgId=994&tblId=DT_AA_001"
    )
    assert out["count"] == len(out["results"]) >= 3
    assert (out["offset"], out["limit"], out["notes"]) == (0, 10, [])
    assert "State Statistical Committee" in out["attribution"]


async def test_search_pages_through_the_results_and_clips_long_descriptions(server):
    first = await call(server, "search_tables", {"limit": 5})
    second = await call(server, "search_tables", {"limit": 5, "offset": 5})
    assert first["count"] == second["count"] == 39
    assert {r["table_id"] for r in first["results"]}.isdisjoint(
        r["table_id"] for r in second["results"]
    )
    everything = await call(server, "search_tables", {"limit": 50})
    lengths = [len(r["description"]) for r in everything["results"]]
    assert max(lengths) == 300
    assert any(r["description"].endswith("…") for r in everything["results"])


async def test_search_can_be_limited_to_a_topic_by_id_or_name(server):
    by_name = await call(server, "search_tables", {"topic": "labour"})
    by_id = await call(server, "search_tables", {"topic": "994_002"})
    assert by_name == by_id
    assert by_name["count"] == 3
    assert {r["topic_id"] for r in by_name["results"]} == {"994_002"}
    with pytest.raises(ToolError, match="No topic matches 'nonsense'"):
        await call(server, "search_tables", {"topic": "nonsense"})


async def test_search_says_which_language_it_searched_when_nothing_matches(server):
    english = await call(server, "search_tables", {"query": "zzzz"})
    assert english["results"] == []
    assert english["notes"] == ["Nothing matched in English. Try other words, or lang=az."]
    azerbaijani = await call(server, "search_tables", {"query": "zzzz", "lang": "az"})
    assert azerbaijani["notes"] == ["Nothing matched in Azerbaijani. Try other words, or lang=en."]


async def test_search_works_in_azerbaijani_with_or_without_diacritics(server):
    for query in ("gəlir", "gelir"):
        out = await call(server, "search_tables", {"query": query, "lang": "az"})
        assert [r["table_id"] for r in out["results"]] == ["DT_BA_005"]
        assert out["results"][0]["name"].startswith("Əhalinin gəlirləri")


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("search_tables", {"limit": 0}),
        ("search_tables", {"limit": 51}),
        ("search_tables", {"offset": -1}),
        ("search_tables", {"lang": "ru"}),
        ("list_topics", {"lang": "ru"}),
        ("get_table_data", {"table_id": "DT_AA_001", "limit": 0}),
        ("get_table_data", {"table_id": "DT_AA_001", "limit": 501}),
        ("get_table_data", {"table_id": "DT_AA_001", "offset": -1}),
    ],
)
async def test_out_of_range_arguments_are_refused(server, tool, arguments):
    with pytest.raises(ToolError):
        await call(server, tool, arguments)


async def test_describe_a_table(server):
    out = await call(server, "describe_table", {"table_id": " dt_aa_001 "})
    assert out["status"] == "ok"
    assert out["reason"] is None
    assert out["table"]["name"] == "Population size (at the beginning of year)"
    assert out["table"]["description"].startswith("This dataset presents")
    assert (out["rows"], out["periods"]) == (160, 32)
    assert (out["first_period"], out["last_period"]) == ("1995", "2026")
    assert (out["period_types"], out["units"]) == (["Y"], ["thsd.person"])
    [dimension] = out["dimensions"]
    assert (dimension["name"], dimension["categories"]) == ("Indicator", 5)
    assert dimension["examples"][0] == "Total population"
    assert out["source"].endswith("tblId=DT_AA_001")
    assert "State Statistical Committee" in out["attribution"]


async def test_describe_can_search_the_categories(server):
    out = await call(server, "describe_table", {"table_id": "DT_AB_051", "category_query": "baku"})
    regions, indicators = out["dimensions"]
    assert regions["matching"] > 0
    assert all("baku" in example.lower() for example in regions["examples"])
    assert (indicators["matching"], indicators["examples"]) == (0, [])
    nothing = await call(
        server, "describe_table", {"table_id": "DT_AB_051", "category_query": "zzz"}
    )
    assert nothing["notes"] == ["No category matches 'zzz'."]


async def test_describe_a_table_the_api_cannot_label_still_shows_what_it_has(server):
    out = await call(server, "describe_table", {"table_id": "DT_AC_011"})
    assert out["status"] == "ambiguous"
    assert "cannot be told apart" in out["reason"]
    assert out["rows"] == 60
    assert out["dimensions"][0]["categories"] == 7


async def test_a_table_that_is_too_large_is_described_without_reading_it(server, portal):
    too_big(portal)
    out = await call(server, "describe_table", {"table_id": "DT_AA_001"})
    assert out["status"] == "too_large"
    assert "reads at most 20 MB" in out["reason"]
    assert "Committee's site" in out["reason"]
    assert (out["rows"], out["dimensions"]) == (None, [])
    assert out["table"]["name"].startswith("Population size")


async def test_describe_refuses_what_it_cannot_find(server):
    with pytest.raises(ToolError, match="catalogue has no table DT_ZZ_999"):
        await call(server, "describe_table", {"table_id": "DT_ZZ_999"})
    with pytest.raises(ToolError, match="not a table id"):
        await call(server, "describe_table", {"table_id": "../x"})
    with pytest.raises(ToolError, match="no table 'DT_AB_074'"):
        await call(server, "describe_table", {"table_id": "DT_AB_074"})


async def test_read_rows_in_long_format_and_page_through_them(server):
    out = await call(server, "get_table_data", {"table_id": "DT_AA_001", "limit": 3})
    assert out["status"] == "ok"
    assert out["columns"] == ["period", "Indicator", "value", "unit"]
    assert out["rows"][0] == ["1995", "Total population", 7643.5, "thsd.person"]
    assert (out["total_rows"], out["offset"], out["next_offset"]) == (160, 0, 3)
    assert "157 more rows: call again with offset=3." in out["notes"]
    assert out["url"].endswith("tblId=DT_AA_001")
    assert out["name"] == "Population size (at the beginning of year)"
    last = await call(
        server, "get_table_data", {"table_id": "DT_AA_001", "offset": 158, "limit": 10}
    )
    assert (len(last["rows"]), last["next_offset"]) == (2, None)
    assert not any("more rows" in note for note in last["notes"])


async def test_rows_can_be_cut_by_period_and_category(server):
    out = await call(
        server,
        "get_table_data",
        {
            "table_id": "DT_AA_001",
            "period_from": 2020,
            "period_to": "2022",
            "where": {"Indicator": "total"},
        },
    )
    assert [(row[0], row[1]) for row in out["rows"]] == [
        ("2020", "Total population"),
        ("2021", "Total population"),
        ("2022", "Total population"),
    ]
    assert (out["total_rows"], out["next_offset"]) == (3, None)


async def test_monthly_periods_are_written_year_and_month(server):
    out = await call(
        server,
        "get_table_data",
        {"table_id": "DT_BE_119", "period_from": "2026-03", "period_to": "2026-04"},
    )
    assert sorted({row[0] for row in out["rows"]}) == ["202603", "202604"]
    assert out["total_rows"] == 4


async def test_dimensions_with_the_same_name_get_distinct_columns_and_can_be_filtered_by_number(
    server,
):
    out = await call(server, "get_table_data", {"table_id": "DT_AC_037", "where": {"2": "higher"}})
    assert out["columns"][:4] == ["period", "Indicator", "Indicator (2)", "value"]
    assert out["rows"]
    assert all("higher" in row[2] for row in out["rows"])
    with pytest.raises(ToolError, match=r"1\. Indicator; 2\. Indicator"):
        await call(server, "get_table_data", {"table_id": "DT_AC_037", "where": {"Indicator": "x"}})


async def test_a_value_the_committee_replaced_with_a_symbol_stays_null_with_its_symbol(server):
    out = await call(
        server,
        "get_table_data",
        {"table_id": "DT_AB_051", "where": {"1": "deputy head", "2": 25}},
    )
    assert "symbol" in out["columns"]
    empty = [row for row in out["rows"] if row[out["columns"].index("value")] is None]
    assert empty
    assert {row[out["columns"].index("symbol")] for row in empty} == {"-"}
    assert any("published as that symbol" in note for note in out["notes"])


async def test_a_table_the_api_cannot_label_returns_no_rows_and_the_link(server):
    out = await call(server, "get_table_data", {"table_id": "DT_AC_011"})
    assert out["status"] == "ambiguous"
    assert "cannot be told apart" in out["reason"]
    assert (out["columns"], out["rows"], out["total_rows"], out["next_offset"]) == ([], [], 0, None)
    assert out["url"].endswith("tblId=DT_AC_011")
    assert out["name"].startswith("Educational attainment of pedagogical staff")


async def test_a_table_that_is_too_large_returns_no_rows_and_the_link(server, portal):
    too_big(portal)
    out = await call(server, "get_table_data", {"table_id": "DT_AA_001"})
    assert (out["status"], out["rows"], out["total_rows"]) == ("too_large", [], 0)
    assert out["name"] is None
    assert "reads at most 20 MB" in out["reason"]
    assert out["url"].endswith("tblId=DT_AA_001")


async def test_filters_that_match_nothing_say_so(server):
    out = await call(server, "get_table_data", {"table_id": "DT_AA_001", "period_from": 2090})
    assert (out["rows"], out["total_rows"]) == ([], 0)
    assert any(note.startswith("No rows matched") for note in out["notes"])


async def test_read_refuses_what_it_cannot_use(server):
    with pytest.raises(ToolError, match="does not name exactly one dimension"):
        await call(server, "get_table_data", {"table_id": "DT_AA_001", "where": {"region": "x"}})
    with pytest.raises(ToolError, match="no table 'DT_AB_074'"):
        await call(server, "get_table_data", {"table_id": "DT_AB_074"})
    with pytest.raises(ToolError, match="not a table id"):
        await call(server, "get_table_data", {"table_id": "bad id"})


async def test_the_language_reaches_the_api(server, portal):
    await call(server, "get_table_data", {"table_id": "DT_AA_001", "lang": "az", "limit": 1})
    assert dict(portal.calls[-1].params) == {"table_id": "DT_AA_001", "lang": "az"}


async def test_every_answer_cites_the_committee(server):
    answers = [
        await call(server, "list_topics"),
        await call(server, "search_tables", {"query": "population"}),
        await call(server, "describe_table", {"table_id": "DT_AA_001"}),
        await call(server, "get_table_data", {"table_id": "DT_AA_001", "limit": 1}),
    ]
    assert all("State Statistical Committee" in answer["attribution"] for answer in answers)
    assert all(answer["source"].startswith("https://www.azstat.gov.az") for answer in answers)
