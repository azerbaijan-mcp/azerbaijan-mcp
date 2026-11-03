import socket
import sys

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError

pytestmark = pytest.mark.anyio

TOOLS = {"define", "search", "browse", "read_entry"}


def entrypoint(**env: str) -> StdioTransport:
    return StdioTransport(command=sys.executable, args=["-m", "azerbaijan_mcp_izahli"], env=env)


def closed_address() -> str:
    """An address on this computer where nothing listens, so no real download is tried."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{probe.getsockname()[1]}/mirror.sqlite.gz"


async def test_the_real_entrypoint_serves_tools_and_explains_a_database_it_cannot_get(tmp_path):
    transport = entrypoint(IZAHLI_CACHE_DIR=str(tmp_path), IZAHLI_DATA_URL=closed_address())
    async with Client(transport) as client:
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
