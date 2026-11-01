from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "rates-2026-10-30.xml"

# cbar.az answers a weekend date with the last business day's sheet (observed for Saturday
# 2026-10-31). The same behaviour is assumed for Sunday 2026-11-01.
SERVED_PATHS = {
    "/currencies/30.10.2026.xml",
    "/currencies/31.10.2026.xml",
    "/currencies/01.11.2026.xml",
}


@dataclass
class Feed:
    http: httpx.AsyncClient
    calls: list[str]


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def sheet_xml() -> bytes:
    return FIXTURE.read_bytes()


@pytest.fixture
def feed(sheet_xml: bytes) -> Feed:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path in SERVED_PATHS:
            return httpx.Response(200, content=sheet_xml)
        return httpx.Response(404)

    return Feed(httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls)
