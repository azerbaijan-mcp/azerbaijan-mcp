import re

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from azerbaijan_mcp_eqanun.client import EqanunClient
from azerbaijan_mcp_eqanun.server import INSTRUCTIONS, create_server

pytestmark = pytest.mark.anyio

TOOLS = {"search_acts", "get_act", "get_article", "find_in_act"}
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
CIVIL_CODE = {"act_id": 46944}


@pytest.fixture
def server(client):
    return create_server(client)


async def call(server, tool, arguments=None):
    async with Client(server) as mcp:
        return (await mcp.call_tool(tool, arguments or {})).structured_content


async def refusal(server, tool, arguments=None) -> str:
    async with Client(server) as mcp:
        with pytest.raises(ToolError) as caught:
            await mcp.call_tool(tool, arguments or {})
    return str(caught.value)


def serve_file(site, data: bytes) -> None:
    """Serve this file for the Civil Code, in place of the saved excerpt."""

    def override(request):
        if request.url.host == "frameworks.e-qanun.az":
            return httpx.Response(200, content=data, headers={"content-type": "text/html"})

    site.override = override


async def test_four_read_only_tools_are_listed(server):
    async with Client(server) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(tools) == TOOLS
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())
    assert all(tool.description for tool in tools.values())
    assert "KMQ" in tools["get_article"].description  # how to read the labels of court decisions


def test_the_instructions_say_where_the_texts_come_from_and_who_is_official():
    assert "e-qanun.az" in INSTRUCTIONS
    assert "State Register of Legal Acts" in INSTRUCTIONS
    assert "repealed" in INSTRUCTIONS


async def test_a_search_lists_acts_with_links_and_names_its_source(server, site):
    out = await call(server, "search_acts", {"query": "mülki məcəllə"})
    assert (out["count"], out["offset"], out["limit"], out["next_offset"]) == (633, 0, 10, 3)
    first = out["results"][0]
    assert first["id"] == 62704
    assert first["url"] == "https://e-qanun.az/framework/62704"
    assert (first["status"], first["accepted"], first["number"]) == ("in_force", "2026-09-21", None)
    assert out["results"][2]["number"] == "674s"
    assert out["source"] == "https://e-qanun.az"
    assert "State Register of Legal Acts" in out["attribution"]
    assert STAMP.fullmatch(out["fetched_at"])
    assert out["notes"] == []
    [url] = site.api_calls("/getDetailSearch")
    assert (url.params["name"], url.params["start"], url.params["length"]) == (
        "mülki məcəllə",
        "0",
        "10",
    )


async def test_paging_asks_the_site_for_the_next_page(server, site):
    out = await call(server, "search_acts", {"query": "x", "limit": 5, "offset": 10})
    [url] = site.api_calls("/getDetailSearch")
    assert (url.params["start"], url.params["length"]) == ("10", "5")
    assert (out["offset"], out["limit"], out["next_offset"]) == (10, 5, 13)


async def test_a_kind_of_act_is_given_in_words_and_becomes_the_sites_ids(server, site):
    out = await call(server, "search_acts", {"query": "mülki", "type": "məcəllə"})
    [url] = site.api_calls("/getDetailSearch")
    assert url.params["array"] == "107"
    assert [act["id"] for act in out["results"]] == [46944, 46945]
    assert (out["count"], out["next_offset"]) == (2, None)
    assert out["notes"] == ["Kinds searched: Məcəllələr."]


async def test_several_kinds_may_match_and_all_are_searched(server, site):
    out = await call(server, "search_acts", {"type": "qanun"})
    [url] = site.api_calls("/getDetailSearch")
    assert url.params["array"] == "28,30,107"
    assert out["notes"][0].startswith("Kinds searched: ")


async def test_a_kind_nobody_has_is_refused_with_a_hint(server):
    message = await refusal(server, "search_acts", {"type": "xyz"})
    assert "No kind of act matches 'xyz'" in message
    assert "qanun" in message


async def test_a_search_in_the_text_needs_words_and_asks_for_the_text(server, site):
    assert "words to look for in the text" in await refusal(
        server, "search_acts", {"field": "text"}
    )
    out = await call(server, "search_acts", {"query": "iddia müddəti", "field": "text"})
    [url] = site.api_calls("/getDetailSearch")
    assert (url.params["title"], url.params["text"]) == ("false", "true")
    assert (out["count"], out["next_offset"]) == (2584, 2)


async def test_repealed_acts_are_asked_for_and_marked(server, site):
    out = await call(server, "search_acts", {"query": "mülki məcəllə", "status": "repealed"})
    [url] = site.api_calls("/getDetailSearch")
    assert url.params["statusId"] == "2"
    assert out["count"] == 13
    assert {act["status"] for act in out["results"]} == {"repealed"}
    assert out["results"][0]["status_text"] == "Ləğv olunmuşdur"


async def test_a_search_that_finds_nothing_says_what_to_try(server, site):
    site.override = lambda request: (
        httpx.Response(200, json={"data": [], "totalCount": 0})
        if request.url.path == "/getDetailSearch"
        else None
    )
    out = await call(server, "search_acts", {"query": "zzz"})
    assert (out["count"], out["results"], out["next_offset"]) == (0, [], None)
    assert "Nothing matched" in out["notes"][0]
    assert "status=all" in out["notes"][0]


async def test_an_act_is_described_and_its_text_starts(server):
    out = await call(server, "get_act", CIVIL_CODE)
    assert out["status"] == "ok"
    assert out["act"]["title"] == "Azərbaycan Respublikasının Mülki Məcəlləsi"
    assert out["act"]["url"] == "https://e-qanun.az/framework/46944"
    assert (out["act"]["accepted"], out["act"]["effective"]) == ("1999-12-28", "2000-09-01")
    assert (out["structure"], out["articles"]) == ("articles", 5)
    assert (out["first_article"], out["last_article"]) == ("1", "14")
    assert out["edition_dates"] == ["2026-07-14", "2026-05-26", "2026-02-27"]
    assert (out["class_codes"], out["publications"]) == (["020.010.000"], [])
    assert out["references"] == [
        {
            "label": "28 dekabr 1999-cu il tarixli 779-IQ nömrəli",
            "act_id": 1,
            "title": None,
            "url": "https://e-qanun.az/framework/1",
        }
    ]
    assert out["text"].startswith("AZƏRBAYCAN RESPUBLİKASININ MÜLKİ MƏCƏLLƏSİ[1]")
    assert (out["total_chars"], out["offset"], out["next_offset"]) == (2147, 0, None)
    assert [note["marker"] for note in out["amendment_notes"]] == [1, 2, 5, 7, 8]
    assert out["amendment_notes"][1]["text"].startswith("20 oktyabr 2006-cı il 167-IIIQD")
    assert any("divided into articles" in note for note in out["notes"])
    assert out["source"] == "https://e-qanun.az/framework/46944"
    assert "unofficial copy" in out["attribution"]
    assert STAMP.fullmatch(out["fetched_at"])


async def test_a_long_text_is_read_in_pieces_with_its_notes(server):
    offset, pieces = 0, []
    while offset is not None:
        out = await call(server, "get_act", {**CIVIL_CODE, "offset": offset, "max_chars": 500})
        pieces.append(out)
        offset = out["next_offset"]
    assert len(pieces) >= 4
    assert all(len(piece["text"]) <= 500 for piece in pieces)
    assert [piece["offset"] for piece in pieces] == sorted({piece["offset"] for piece in pieces})
    assert any("more characters: call again with offset=" in n for n in pieces[0]["notes"])
    assert not any("more characters" in n for n in pieces[-1]["notes"])
    assert "\n".join(piece["text"] for piece in pieces).count("Maddə ") == 5
    markers = [note["marker"] for piece in pieces for note in piece["amendment_notes"]]
    assert markers == [1, 2, 5, 7, 8]
    # the one link lies in the first piece and is not repeated in the others
    assert [link["act_id"] for piece in pieces for link in piece["references"]] == [1]


async def test_an_act_without_articles_is_read_as_paragraphs(server):
    out = await call(server, "get_act", {"act_id": 42904})
    assert (out["structure"], out["articles"], out["first_article"]) == ("paragraphs", None, None)
    assert out["act"]["type"] == "Ədliyyə Nazirliyi"
    assert out["act"]["number"] == "17-N"
    assert out["register_date"] == "2019-07-15"
    assert out["edition_dates"] == ["2020-10-05", "2019-07-15"]
    assert "№ 17-N" in out["text"]
    assert not any("divided into articles" in note for note in out["notes"])
    # the decision cites two other acts, and the site says what each of them is
    assert [(link["act_id"], link["url"]) for link in out["references"]] == [
        (41166, "https://e-qanun.az/framework/41166"),
        (53759, "https://e-qanun.az/framework/53759"),
    ]
    assert out["references"][1]["title"].endswith("203s nömrəli Sərəncamı")


async def test_a_repealed_act_is_flagged_and_its_publications_listed(server, site):
    site.files["41/f_41807.html"] = "act_code.html"
    out = await call(server, "get_act", {"act_id": 41807})
    assert out["act"]["status"] == "repealed"
    assert "repealed" in out["notes"][0]
    assert "do not present it as current law" in out["notes"][0]
    assert out["act"]["number"] == "107"
    assert [p["source"] for p in out["publications"]] == [
        "Xalq Qəzeti",
        "Azərbaycan Respublikasının Qanunvericilik Toplusu",
    ]
    assert out["publications"][0]["details"] == [
        "Dərc olunma tarixi: 20-03-2019",
        "Nəşr Nömrəsi: 64",
    ]


async def test_a_file_too_big_to_read_still_gets_its_details_and_a_link(site):
    client = EqanunClient(http=site.http, min_interval=0, max_bytes=1000)
    out = await call(create_server(client), "get_act", CIVIL_CODE)
    assert out["status"] == "too_large"
    assert "this server reads at most" in out["reason"]
    assert "Read the act on e-qanun.az instead" in out["reason"]
    assert out["text"] is None
    assert (out["amendment_notes"], out["references"]) == ([], [])
    assert (out["structure"], out["articles"], out["total_chars"]) == (None, None, None)
    assert out["act"]["title"] == "Azərbaycan Respublikasının Mülki Məcəlləsi"
    assert out["edition_dates"][0] == "2026-07-14"
    assert out["source"] == "https://e-qanun.az/framework/46944"


async def test_an_act_the_site_does_not_have_is_refused(server):
    assert "no act 999999999" in await refusal(server, "get_act", {"act_id": 999999999})


async def test_an_article_comes_with_its_notes_and_its_neighbours(server):
    out = await call(server, "get_article", {**CIVIL_CODE, "article": "1"})
    assert out["article"] == "1"
    assert out["heading"].startswith("Maddə 1. Azərbaycan Respublikası Mülki Məcəlləsinin məqsəd")
    assert out["text"].startswith("1.1. Bu Məcəllənin məqsədi")
    assert [note["marker"] for note in out["amendment_notes"]] == [2]
    assert "[2]" in out["text"]
    assert (out["previous_article"], out["next_article"]) == (None, "2")
    assert (out["offset"], out["next_offset"], out["total_chars"]) == (0, None, 631)
    assert out["act"]["url"] == out["source"] == "https://e-qanun.az/framework/46944"
    assert STAMP.fullmatch(out["fetched_at"])
    assert out["notes"] == []


async def test_the_acts_an_article_links_to_are_listed_with_their_ids(server, site, word):
    serve_file(
        site,
        word(
            [
                "Maddə 373. Limitation periods<<#KM2>>",
                "373.1. Ten years. <<KMQ23|53598|Plenum decision of 15 February 2023>>",
            ]
        ),
    )
    out = await call(server, "get_article", {**CIVIL_CODE, "article": 373})
    assert out["heading"] == "Maddə 373. Limitation periods KM2"
    assert out["text"] == "373.1. Ten years. KMQ23"
    assert out["references"] == [
        {
            "label": "KMQ23",
            "act_id": 53598,
            "title": "Plenum decision of 15 February 2023",
            "url": "https://e-qanun.az/framework/53598",
        }
    ]


async def test_a_note_in_an_articles_heading_comes_with_it(server):
    out = await call(server, "get_article", {**CIVIL_CODE, "article": "Maddə 13."})
    assert out["article"] == "13"
    assert out["heading"] == "Maddə 13. Sahibkarlıq fəaliyyəti[7]"
    assert [note["marker"] for note in out["amendment_notes"]] == [7, 8]
    assert "fəsil" not in out["text"]
    assert (out["previous_article"], out["next_article"]) == ("6", "14")


async def test_a_number_may_be_given_as_a_number_or_name_a_part_of_an_article(server):
    assert (await call(server, "get_article", {**CIVIL_CODE, "article": 6}))["article"] == "6"
    out = await call(server, "get_article", {**CIVIL_CODE, "article": "13.1"})
    assert out["article"] == "13"
    assert out["notes"] == ["13.1 is part 1 of article 13."]


async def test_an_article_the_act_does_not_have_is_refused_with_the_range_it_has(server):
    message = await refusal(server, "get_article", {**CIVIL_CODE, "article": "99"})
    assert "The act has no article 99." in message
    assert "run from 1 to 14 (5 in all)" in message


async def test_something_that_is_not_an_article_number_is_refused(server):
    message = await refusal(server, "get_article", {**CIVIL_CODE, "article": "abc"})
    assert "not an article number" in message


async def test_an_act_without_articles_points_to_the_other_tools(server):
    message = await refusal(server, "get_article", {"act_id": 42904, "article": "1"})
    assert "not divided into articles" in message
    assert "get_act" in message
    assert "find_in_act" in message


async def test_an_article_of_a_repealed_act_carries_the_warning(server, site):
    site.files["41/f_41807.html"] = "act_code.html"
    out = await call(server, "get_article", {"act_id": 41807, "article": "1"})
    assert "repealed" in out["notes"][0]


async def test_a_long_article_is_read_in_pieces_each_with_its_own_notes(server, site, word):
    lines = [f"1.{n}. " + "lorem ipsum " * 20 + ("{2}" if n == 40 else "") for n in range(1, 41)]
    serve_file(
        site, word(["Maddə 1. Long article{1}", *lines], {1: "heading note", 2: "last note"})
    )
    offset, pieces = 0, []
    while offset is not None:
        arguments = {**CIVIL_CODE, "article": 1, "offset": offset, "max_chars": 3000}
        pieces.append(await call(server, "get_article", arguments))
        offset = pieces[-1]["next_offset"]
    assert len(pieces) >= 3
    assert all(len(piece["text"]) <= 3000 for piece in pieces)
    assert len({piece["total_chars"] for piece in pieces}) == 1
    # the heading comes with every piece, so its note does too; the last note only at the end
    assert [n["marker"] for n in pieces[0]["amendment_notes"]] == [1]
    assert [n["marker"] for n in pieces[-1]["amendment_notes"]] == [1, 2]
    assert any("more characters: call again with offset=" in n for n in pieces[0]["notes"])
    assert not any("more characters" in n for n in pieces[-1]["notes"])
    expected = "\n".join(re.sub(r"\s+", " ", line.replace("{2}", "[2]")).strip() for line in lines)
    assert "\n".join(piece["text"] for piece in pieces) == expected


async def test_words_are_found_in_the_articles_of_an_act(server):
    out = await call(server, "find_in_act", {**CIVIL_CODE, "query": "mulki"})
    assert (out["unit"], out["count"], out["next_offset"]) == ("article", 4, None)
    assert [(hit["article"], hit["matches"]) for hit in out["results"]] == [
        ("1", 5),
        ("14", 5),
        ("2", 3),
        ("6", 2),
    ]
    first = out["results"][0]
    assert first["heading"].startswith("Maddə 1. Azərbaycan")
    assert "mülki" in first["snippet"].lower()
    assert first["position"] > 0
    assert out["act"]["id"] == 46944
    assert out["source"] == "https://e-qanun.az/framework/46944"
    assert STAMP.fullmatch(out["fetched_at"])


async def test_a_word_form_with_a_different_ending_is_still_found(server):
    out = await call(server, "find_in_act", {**CIVIL_CODE, "query": "mülki qanunvericilik"})
    assert {hit["article"] for hit in out["results"]} == {"2", "6", "14"}


async def test_the_results_of_a_search_in_an_act_are_paged(server):
    first = await call(server, "find_in_act", {**CIVIL_CODE, "query": "mülki", "limit": 3})
    assert (first["count"], first["next_offset"], len(first["results"])) == (4, 3, 3)
    last = await call(server, "find_in_act", {**CIVIL_CODE, "query": "mülki", "offset": 3})
    assert [hit["article"] for hit in last["results"]] == ["6"]
    assert last["next_offset"] is None


async def test_no_match_in_an_act_says_so(server):
    out = await call(server, "find_in_act", {**CIVIL_CODE, "query": "hamiləlik"})
    assert (out["count"], out["results"]) == (0, [])
    assert "Nothing matched" in out["notes"][0]


async def test_in_an_act_without_articles_each_result_is_a_paragraph_to_read_on_from(server):
    out = await call(server, "find_in_act", {"act_id": 42904, "query": "qaydaları"})
    assert (out["unit"], out["count"]) == ("paragraph", 4)
    assert any("no articles" in note for note in out["notes"])
    hit = out["results"][-1]
    assert hit["article"] is None
    there = await call(server, "get_act", {"act_id": 42904, "offset": hit["position"]})
    assert there["text"].startswith(hit["heading"][:30])


async def test_a_blank_search_is_refused(server):
    assert "Give the words" in await refusal(server, "find_in_act", {**CIVIL_CODE, "query": "  "})
    async with Client(server) as mcp:
        with pytest.raises(ToolError):
            await mcp.call_tool("find_in_act", {**CIVIL_CODE, "query": ""})


async def test_a_site_that_turns_the_server_away_is_reported_and_not_worked_around(server, site):
    site.override = lambda request: httpx.Response(429, text="slow down")
    message = await refusal(server, "search_acts", {"query": "mülki"})
    assert "refuses requests" in message
    assert "does not retry or work around it" in message
    assert len(site.calls) == 1


@pytest.mark.parametrize(
    ("status", "said"),
    [("Qüvvəsini itirmişdir", "as 'Qüvvəsini itirmişdir'"), ("", "not at all")],
)
async def test_a_status_the_server_does_not_know_is_passed_on_and_checked_against_the_site(
    server, site, load, status, said
):
    body = load("framework_code.json")
    body["data"]["requisite"]["statusName"] = status
    site.override = lambda request: (
        httpx.Response(200, json=body) if request.url.path == "/framework/46944" else None
    )
    out = await call(server, "get_article", {**CIVIL_CODE, "article": 1})
    assert out["act"]["status"] == "unknown"
    assert out["notes"] == [
        f"The site gives this act's status {said}; check it on https://e-qanun.az/framework/46944."
    ]


TOOLS_THAT_READ_THE_FILE = [
    ("get_act", {}),
    ("get_article", {"article": 1}),
    ("find_in_act", {"query": "mülki"}),
]


@pytest.mark.parametrize(("tool", "extra"), TOOLS_THAT_READ_THE_FILE)
async def test_a_file_the_site_answers_oddly_is_reported_by_every_tool(server, site, tool, extra):
    site.override = lambda request: (
        httpx.Response(418) if request.url.host == "frameworks.e-qanun.az" else None
    )
    assert "answered HTTP 418" in await refusal(server, tool, {**CIVIL_CODE, **extra})


@pytest.mark.parametrize(("tool", "extra"), TOOLS_THAT_READ_THE_FILE[1:])
async def test_a_file_too_big_to_read_is_refused_with_a_link_by_the_tools_that_need_it(
    site, tool, extra
):
    client = EqanunClient(http=site.http, min_interval=0, max_bytes=1000)
    message = await refusal(create_server(client), tool, {**CIVIL_CODE, **extra})
    assert "this server reads at most" in message
    assert "https://e-qanun.az/framework/46944" in message
