import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

pytestmark = pytest.mark.anyio


async def test_the_real_entrypoint_serves_tools_over_stdio():
    transport = StdioTransport(command=sys.executable, args=["-m", "azerbaijan_mcp_utils"])
    async with Client(transport) as client:
        names = {tool.name for tool in await client.list_tools()}
        holidays = (await client.call_tool("holidays", {"year": 2026})).structured_content
    assert names == {
        "validate_iban",
        "format_phone",
        "azn_in_words",
        "transliterate",
        "holidays",
        "working_days",
    }
    assert holidays["five_day_working_days"] == 241
