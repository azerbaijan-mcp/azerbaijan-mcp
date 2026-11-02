import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from azerbaijan_mcp_utils.server import create_server

pytestmark = pytest.mark.anyio

TOOLS = {
    "validate_iban",
    "format_phone",
    "azn_in_words",
    "transliterate",
    "holidays",
    "working_days",
}
REGISTRY_EXAMPLE = "AZ21NABZ00000000137010001944"
URL_2026 = "https://sosial.gov.az/faydali/istehsalat-teqvimi/2026-ci-ilin-istehsalat-teqvimi"
URL_2025 = "https://sosial.gov.az/faydali/istehsalat-teqvimi/2025-ci-ilin-istehsalat-teqvimi"


@pytest.fixture
def server():
    return create_server()


async def call(server, tool, arguments):
    async with Client(server) as mcp:
        return (await mcp.call_tool(tool, arguments)).structured_content


async def test_six_offline_read_only_tools_are_listed(server):
    async with Client(server) as mcp:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(tools) == TOOLS
    for tool in tools.values():
        assert tool.description
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.open_world_hint is False


async def test_validate_iban(server):
    good = await call(server, "validate_iban", {"iban": "az21 nabz 0000 0000 1370 1000 1944"})
    assert good["valid"] is True
    assert good["iban"] == REGISTRY_EXAMPLE
    assert good["formatted"] == "AZ21 NABZ 0000 0000 1370 1000 1944"
    assert (good["bank_code"], good["check_digits"]) == ("NABZ", "21")
    assert "ISO 13616" in good["source"]
    bad = await call(server, "validate_iban", {"iban": REGISTRY_EXAMPLE[:-1] + "5"})
    assert bad["valid"] is False
    assert "mod-97" in bad["problems"][0]
    other = await call(server, "validate_iban", {"iban": "GB82WEST12345698765432"})
    assert other["valid"] is False
    assert other["formatted"] is None


async def test_format_phone(server):
    mobile = await call(server, "format_phone", {"number": "050 123 45 67"})
    assert mobile["valid_format"] is True
    assert (mobile["e164"], mobile["kind"]) == ("+994501234567", "mobile")
    assert mobile["international"] == "+994 50 123 45 67"
    landline = await call(server, "format_phone", {"number": "(012) 345-67-89"})
    assert (landline["kind"], landline["area"]) == ("landline", "Baku")
    unknown = await call(server, "format_phone", {"number": "+994 40 123 45 67"})
    assert unknown["kind"] == "unknown"
    assert unknown["notes"]
    wrong = await call(server, "format_phone", {"number": "+90 532 123 45 67"})
    assert wrong["valid_format"] is False
    assert wrong["kind"] is None
    assert "Numbering Plan" in wrong["source"]


@pytest.mark.parametrize("amount", ["1234.56", 1234.56, "1 234,56"])
async def test_amounts_in_words_in_three_languages(server, amount):
    az = await call(server, "azn_in_words", {"amount": amount})
    assert az["text"] == "min iki yüz otuz dörd manat əlli altı qəpik"
    assert (az["amount"], az["manat"], az["qepik"], az["lang"]) == ("1234.56", 1234, 56, "az")
    en = await call(server, "azn_in_words", {"amount": amount, "lang": "en"})
    assert en["text"] == "one thousand two hundred thirty-four manat and fifty-six qəpik"
    ru = await call(server, "azn_in_words", {"amount": amount, "lang": "ru"})
    assert ru["text"] == "одна тысяча двести тридцать четыре маната пятьдесят шесть гяпиков"


async def test_the_bir_min_style_and_whole_numbers(server):
    out = await call(server, "azn_in_words", {"amount": "1547.32", "bir_min": True})
    assert out["text"] == "bir min beş yüz qırx yeddi manat otuz iki qəpik"
    assert (await call(server, "azn_in_words", {"amount": 5}))["text"] == "beş manat"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"amount": "1.234"}, "at most two decimals"),
        ({"amount": -5}, "must not be negative"),
        ({"amount": "abc"}, "is not an amount"),
        ({"amount": 1e16}, "is not an amount"),
        ({"amount": "1000000000000"}, "below one trillion"),
        ({"amount": 5, "lang": "de"}, ""),
    ],
)
async def test_amounts_that_cannot_be_written_are_tool_errors(server, arguments, message):
    with pytest.raises(ToolError, match=message or None):
        await call(server, "azn_in_words", arguments)


async def test_transliterate_both_ways(server):
    out = await call(
        server, "transliterate", {"text": "Azərbaycan", "direction": "latin_to_cyrillic"}
    )
    assert out["result"] == "Азәрбајҹан"
    assert (out["unchanged"], out["notes"]) == ("", [])
    back = await call(
        server, "transliterate", {"text": "Азәрбајҹан", "direction": "cyrillic_to_latin"}
    )
    assert back["result"] == "Azərbaycan"
    mixed = await call(server, "transliterate", {"text": "Wi-Fi", "direction": "latin_to_cyrillic"})
    assert (mixed["result"], mixed["unchanged"]) == ("Wи-Фи", "W")
    assert mixed["notes"] == ["Letters outside the 32-letter tables were left unchanged."]


async def test_transliterate_refuses_very_long_text_and_unknown_directions(server):
    with pytest.raises(ToolError):
        await call(
            server, "transliterate", {"text": "a" * 10_001, "direction": "latin_to_cyrillic"}
        )
    with pytest.raises(ToolError):
        await call(server, "transliterate", {"text": "a", "direction": "greek"})


async def test_holidays_of_2026_come_with_their_decisions(server):
    out = await call(server, "holidays", {"year": 2026})
    assert out["year"] == 2026
    assert "11 December 2025, No. 3-17/3-5-31/2025" in out["decision"]
    assert out["url"] == URL_2026
    assert "No. 362" in out["cabinet_decisions"][0]
    assert out["five_day_working_days"] == 241
    days = {day["date"]: day for day in out["days"]}
    assert len(days) == 17
    novruz = days["2026-03-20"]
    assert novruz["names_en"] == ["Novruz", "Ramadan Bayram (Eid al-Fitr)"]
    assert novruz["names_az"] == ["Novruz bayramı", "Ramazan bayramı"]
    assert (novruz["kinds"], novruz["weekday"]) == (["decree", "decree"], "Friday")
    assert days["2026-05-28"]["kinds"] == ["decree", "fixed"]
    assert days["2026-01-20"]["kinds"] == ["mourning"]
    assert out["rest_days"]["five_day"][-1] == "2026-11-10"
    assert "2026-03-30" in out["rest_days"]["five_day"]
    assert "2026-03-30" not in out["rest_days"]["six_day"]
    assert out["days"] == sorted(out["days"], key=lambda day: day["date"])
    assert out["notes"]


async def test_holidays_of_2025_include_the_municipal_election_day(server):
    out = await call(server, "holidays", {"year": 2025})
    days = {day["date"]: day for day in out["days"]}
    assert days["2025-01-29"]["kinds"] == ["election"]
    assert out["five_day_working_days"] == 239
    assert any("No. 521" in decision for decision in out["cabinet_decisions"])


@pytest.mark.parametrize("year", [2099, 1800, 2300])
async def test_holidays_of_a_year_without_a_calendar_are_refused(server, year):
    with pytest.raises(ToolError):
        await call(server, "holidays", {"year": year})


async def test_the_refusal_names_the_years_that_are_loaded(server):
    with pytest.raises(ToolError, match=r"no official calendar for 2099.*Calendars loaded: 2025"):
        await call(server, "holidays", {"year": 2099})


async def test_counting_working_days(server):
    out = await call(server, "working_days", {"start": "2026-03-16", "end": "2026-03-31"})
    assert (out["calendar_days"], out["working_days"], out["week"]) == (16, 5, "five_day")
    assert len(out["non_working_days"]) == 11
    first = out["non_working_days"][0]
    assert (first["date"], first["weekday"]) == ("2026-03-20", "Friday")
    assert first["reasons"] == ["Novruz", "Ramadan Bayram (Eid al-Fitr)"]
    assert out["sources"] == [URL_2026]
    six = await call(
        server, "working_days", {"start": "2026-03-16", "end": "2026-03-31", "week": "six_day"}
    )
    assert six["working_days"] == 7


async def test_a_range_across_two_years_cites_both_calendars(server):
    out = await call(server, "working_days", {"start": " 2025-12-29 ", "end": "2026-01-05"})
    assert out["working_days"] == 3
    assert (out["start"], out["end"]) == ("2025-12-29", "2026-01-05")
    assert out["sources"] == [URL_2025, URL_2026]


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"start": "16 March", "end": "2026-03-31"}, "start must be a date"),
        ({"start": "2026-03-16", "end": "2026-13-01"}, "end must be a date"),
        ({"start": "2026-03-31", "end": "2026-03-16"}, "end date is before"),
        ({"start": "2099-01-01", "end": "2099-01-05"}, "no official calendar for 2099"),
        ({"start": "2000-01-01", "end": "2026-01-01"}, "longer than 3660 days"),
        ({"start": "2026-03-16", "end": "2026-03-31", "week": "four_day"}, ""),
    ],
)
async def test_bad_ranges_are_tool_errors(server, arguments, message):
    with pytest.raises(ToolError, match=message or None):
        await call(server, "working_days", arguments)
