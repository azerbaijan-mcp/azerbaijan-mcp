from datetime import date

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from azerbaijan_mcp_cbar.client import CbarClient
from azerbaijan_mcp_cbar.server import create_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def server(feed):
    return create_server(CbarClient(http=feed.http, retry_delay=0, today=lambda: date(2026, 11, 1)))


async def call(server, tool, arguments):
    async with Client(server) as client:
        return (await client.call_tool(tool, arguments)).structured_content


async def test_both_tools_are_listed_and_read_only(server):
    async with Client(server) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    assert set(tools) == {"get_rates", "convert"}
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.values())


async def test_get_rates_filters_in_requested_order(server):
    out = await call(
        server, "get_rates", {"date": "2026-10-30", "codes": ["rub", "usd", "xyz", "azn"]}
    )
    assert [r["code"] for r in out["rates"]] == ["RUB", "USD"]
    assert out["unknown_codes"] == ["XYZ"]
    rub = out["rates"][0]
    assert (rub["nominal"], rub["value"], rub["per_unit"]) == (100, 2.0923, 0.020923)
    assert rub["name_en"] == "Russian Ruble"
    assert out["sheet_date"] == "2026-10-30"
    assert out["note"] is None
    assert "cbar.az" in out["attribution"]


async def test_get_rates_without_codes_lists_everything_currencies_first(server):
    out = await call(server, "get_rates", {"date": "2026-10-30"})
    kinds = [r["kind"] for r in out["rates"]]
    assert len(kinds) == 42
    assert kinds == sorted(kinds, key=lambda kind: kind != "currency")


async def test_default_date_is_today_in_baku_and_explains_the_weekend(server):
    out = await call(server, "get_rates", {"codes": ["USD"]})
    assert out["requested_date"] == "2026-11-01"
    assert out["sheet_date"] == "2026-10-30"
    assert "weekends and public holidays" in out["note"]


async def test_convert_goes_through_azn(server):
    usd = await call(
        server,
        "convert",
        {"amount": 100, "from_currency": "usd", "to_currency": "azn", "date": "2026-10-30"},
    )
    assert usd["result"] == pytest.approx(170.0)
    rub = await call(
        server,
        "convert",
        {"amount": 1000, "from_currency": "RUB", "to_currency": "AZN", "date": "2026-10-30"},
    )
    assert rub["result"] == pytest.approx(20.923)
    cross = await call(
        server,
        "convert",
        {"amount": 1, "from_currency": "USD", "to_currency": "EUR", "date": "2026-10-30"},
    )
    assert cross["rate"] == pytest.approx(1.7 / 1.9019, rel=1e-9)


async def test_convert_accepts_metals_per_troy_ounce(server):
    out = await call(
        server,
        "convert",
        {"amount": 1, "from_currency": "XAU", "to_currency": "AZN", "date": "2026-10-30"},
    )
    assert out["result"] == pytest.approx(6796.43)


@pytest.mark.parametrize(
    ("tool", "arguments", "message"),
    [
        (
            "convert",
            {"amount": 1, "from_currency": "XYZ", "to_currency": "AZN", "date": "2026-10-30"},
            "Unknown currency code",
        ),
        ("get_rates", {"date": "yesterday"}, "Invalid date"),
        ("get_rates", {"date": "2026-10-29"}, "no rate sheet"),
    ],
)
async def test_bad_input_becomes_a_tool_error(server, tool, arguments, message):
    with pytest.raises(ToolError, match=message):
        await call(server, tool, arguments)
