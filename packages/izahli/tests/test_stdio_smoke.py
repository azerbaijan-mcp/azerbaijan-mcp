import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError

pytestmark = pytest.mark.anyio

TOOLS = {"define", "search", "browse", "read_entry"}


def entrypoint(**env: str) -> StdioTransport:
    return StdioTransport(command=sys.executable, args=["-m", "azerbaijan_mcp_izahli"], env=env)


async def test_the_real_entrypoint_serves_tools_and_explains_a_missing_database(tmp_path):
    async with Client(entrypoint(IZAHLI_CACHE_DIR=str(tmp_path))) as client:
        assert {tool.name for tool in await client.list_tools()} == TOOLS
        with pytest.raises(ToolError, match="IZAHLI_DB"):
            await client.call_tool("define", {"word": "su"})


async def test_the_real_entrypoint_answers_from_the_database_the_environment_names(
    source_db, tmp_path
):
    transport = entrypoint(IZAHLI_DB=str(source_db), IZAHLI_CACHE_DIR=str(tmp_path))
    async with Client(transport) as client:
        result = await client.call_tool("define", {"word": "kitab"})
    assert result.structured_content["entries"][0]["headword"] == "KİTAB"
