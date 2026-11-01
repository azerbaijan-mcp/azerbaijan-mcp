import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest

from azerbaijan_mcp_azstat.client import AzstatClient

FIXTURES = Path(__file__).parent / "fixtures"
API = "/AsisOpenDataApi"
JSON = {"content-type": "application/json;charset=UTF-8"}
NOT_FOUND = "Göstərilən table_id tapılmadı."

# Table id -> the saved answer. They are trimmed copies of real answers, except DT_AA_001 and
# DT_BE_119, which are whole. DT_AC_011 is a table the API leaves ambiguous.
TABLES = {
    "DT_AA_001": "data_DT_AA_001.json",
    "DT_AB_051": "data_DT_AB_051.json",
    "DT_AC_011": "data_DT_AC_011.json",
    "DT_AC_037": "data_DT_AC_037.json",
    "DT_BE_119": "data_DT_BE_119.json",
}


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> dict[str, Any]:
    return json.loads(fixture_bytes(name))


@dataclass
class Portal:
    """A fake azstat.gov.az API that serves the saved answers and records every request.

    Set `override` to answer a request differently; return None to fall through.
    """

    override: Callable[[httpx.Request], httpx.Response | None] | None = None
    calls: list[httpx.URL] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url)
        if self.override is not None and (response := self.override(request)) is not None:
            return response
        url = request.url
        lang = url.params.get("lang")
        if url.host != "www.azstat.gov.az":
            return httpx.Response(404)
        if lang not in ("en", "az"):
            message = "lang yalnız az və ya en ola bilər."
            return httpx.Response(400, json={"success": False, "message": message})
        if url.path == f"{API}/tables":
            return httpx.Response(200, content=fixture_bytes(f"tables_{lang}.json"), headers=JSON)
        if url.path == f"{API}/data":
            name = TABLES.get(url.params.get("table_id", ""))
            if name is None:
                return httpx.Response(400, json={"success": False, "message": NOT_FOUND})
            return httpx.Response(200, content=fixture_bytes(name), headers=JSON)
        return httpx.Response(404, json={"success": False, "message": "Resurs tapılmadı."})

    @property
    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def tables_requested(self) -> list[str]:
        return [u.params["table_id"] for u in self.calls if u.path.endswith("/data")]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def load() -> Callable[[str], dict[str, Any]]:
    """A saved answer, parsed."""
    return fixture_json


@pytest.fixture
def portal() -> Portal:
    return Portal()


@pytest.fixture
def client(portal: Portal) -> AzstatClient:
    return AzstatClient(http=portal.http, min_interval=0, retry_delay=0)
