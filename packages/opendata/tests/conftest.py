import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from azerbaijan_mcp_opendata.client import OpenDataClient

FIXTURES = Path(__file__).parent / "fixtures"

DATASET_ID = "48b43a92-0821-40b6-884d-c41606907a8b"
DATASET_NAME = "income-and-expenditure-of-the-population--in-current-prices--mln--"
PORTAL_CSV = "45abb80f-313a-495f-81ab-f0585448226d"
AZSTAT_CSV = "cef84040-6902-40ab-9300-6d66e44d3695"
AZSTAT_JSON = "4368e061-18ac-4479-8a0e-c33aaea2c29b"

API = "/api/3/action"
JSON = {"content-type": "application/json"}
CSV = {"content-type": "text/csv"}


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def fixture_json(name: str) -> dict[str, Any]:
    return json.loads(fixture_bytes(name))


@dataclass
class Portal:
    """A fake opendata.az that serves the saved responses and records every request.

    The CKAN API answers on admin.opendata.az. The first CSV of the dataset sits on the same host
    and redirects to its storage host, as the real portal does; the other files live on azstat.
    Set `show` to change the dataset, or `override` to answer a request differently.
    """

    show: dict[str, Any] = field(default_factory=lambda: fixture_json("show_population.json"))
    override: Callable[[httpx.Request], httpx.Response | None] | None = None
    calls: list[httpx.URL] = field(default_factory=list)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url)
        if self.override is not None and (response := self.override(request)) is not None:
            return response
        url = request.url
        if url.host == "admin.opendata.az" and url.path == f"{API}/package_search":
            facets = url.params.get("rows") == "0"
            name = "facets.json" if facets else "search_population.json"
            return httpx.Response(200, content=fixture_bytes(name), headers=JSON)
        if url.host == "admin.opendata.az" and url.path == f"{API}/package_show":
            if url.params.get("id") in (DATASET_ID, DATASET_NAME):
                return httpx.Response(200, json=self.show)
            error = {"message": "Not found", "__type": "Not Found Error"}
            return httpx.Response(404, json={"success": False, "error": error})
        if url.host == "admin.opendata.az" and "/download/" in url.path:
            target = "https://data-storage.opendata.az/files/population.csv"
            return httpx.Response(302, headers={"location": target})
        if url.host == "data-storage.opendata.az":
            return httpx.Response(200, content=fixture_bytes("portal_style.csv"), headers=CSV)
        if url.host == "www.azstat.gov.az" and url.path == "/AsisOpenDataApi/csv":
            return httpx.Response(200, content=fixture_bytes("azstat.csv"), headers=CSV)
        if url.host == "www.azstat.gov.az" and url.path == "/AsisOpenDataApi/data":
            return httpx.Response(200, content=fixture_bytes("azstat_data.json"), headers=JSON)
        return httpx.Response(404)

    @property
    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def resource(self, resource_id: str) -> dict[str, Any]:
        return next(r for r in self.show["result"]["resources"] if r["id"] == resource_id)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def read() -> Callable[[str], bytes]:
    """Bytes of a saved fixture file."""
    return fixture_bytes


@pytest.fixture(scope="session")
def ids() -> SimpleNamespace:
    """Ids of the dataset and its three files in the saved package_show response."""
    return SimpleNamespace(
        dataset=DATASET_ID,
        name=DATASET_NAME,
        portal_csv=PORTAL_CSV,
        azstat_csv=AZSTAT_CSV,
        azstat_json=AZSTAT_JSON,
    )


@pytest.fixture
def portal() -> Portal:
    return Portal()


@pytest.fixture
def client(portal: Portal) -> OpenDataClient:
    return OpenDataClient(http=portal.http, min_interval=0, retry_delay=0)


@pytest.fixture(scope="session")
def show_record() -> dict[str, Any]:
    return fixture_json("show_population.json")["result"]
