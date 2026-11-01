import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

pytestmark = pytest.mark.anyio


async def test_the_real_entrypoint_serves_tools_over_stdio():
    transport = StdioTransport(command=sys.executable, args=["-m", "azerbaijan_mcp_azstat"])
    async with Client(transport) as client:
        names = {tool.name for tool in await client.list_tools()}
    assert names == {"list_topics", "search_tables", "describe_table", "get_table_data"}
