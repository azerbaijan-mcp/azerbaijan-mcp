import json

import httpx
import pytest

from azerbaijan_mcp_azstat import __version__
from azerbaijan_mcp_azstat import client as client_module
from azerbaijan_mcp_azstat.client import TABLE_CACHE_SIZE, AzstatClient
from azerbaijan_mcp_azstat.errors import (
    AzstatError,
    EndpointBlocked,
    NotFound,
    TableTooLarge,
    UnexpectedShape,
)

pytestmark = pytest.mark.anyio

NOT_FOUND = "Göstərilən table_id tapılmadı."


class Clock:
    """A fake clock whose sleep moves time forward and remembers how long it was asked to wait."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_client(handler, **kwargs) -> AzstatClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs.setdefault("min_interval", 0)
    kwargs.setdefault("retry_delay", 0)
    return AzstatClient(http=http, **kwargs)


def timed(portal, clock) -> AzstatClient:
    return AzstatClient(http=portal.http, min_interval=0, now=clock.time, sleep=clock.sleep)


def serve_any_table(portal, load):
    """Answer every table request with the population table, whatever its id."""

    def override(request):
        if request.url.path.endswith("/data"):
            return httpx.Response(200, json=load("data_DT_AA_001.json"))

    portal.override = override


async def test_the_catalogue_is_cached_per_language_for_an_hour(portal):
    clock = Clock()
    client = timed(portal, clock)
    assert len(await client.catalogue("en")) == 39
    assert portal.calls[0].path == "/AsisOpenDataApi/tables"
    assert dict(portal.calls[0].params) == {"lang": "en"}
    await client.catalogue("en")
    assert len(portal.calls) == 1
    await client.catalogue("az")
    assert len(portal.calls) == 2
    clock.now += 3599
    await client.catalogue("en")
    assert len(portal.calls) == 2
    clock.now += 2
    await client.catalogue("en")
    assert len(portal.calls) == 3


async def test_a_table_is_cached_for_half_an_hour(portal):
    clock = Clock()
    client = timed(portal, clock)
    table = await client.table("DT_AA_001", "en")
    assert len(table.rows) == 160
    assert portal.calls[0].path == "/AsisOpenDataApi/data"
    assert dict(portal.calls[0].params) == {"table_id": "DT_AA_001", "lang": "en"}
    clock.now += 1799
    await client.table("DT_AA_001", "en")
    assert len(portal.calls) == 1
    await client.table("DT_AA_001", "az")
    assert len(portal.calls) == 2
    clock.now += 2
    await client.table("DT_AA_001", "en")
    assert len(portal.calls) == 3


async def test_the_cache_keeps_a_few_tables_and_drops_the_least_recently_used(portal, load):
    serve_any_table(portal, load)
    client = AzstatClient(http=portal.http, min_interval=0)
    ids = [f"DT_T_{number:03d}" for number in range(TABLE_CACHE_SIZE + 1)]
    for table_id in ids[:TABLE_CACHE_SIZE]:
        await client.table(table_id, "en")
    await client.table(ids[0], "en")
    assert len(portal.calls) == TABLE_CACHE_SIZE
    await client.table(ids[-1], "en")
    assert len(portal.calls) == TABLE_CACHE_SIZE + 1
    await client.table(ids[0], "en")
    assert len(portal.calls) == TABLE_CACHE_SIZE + 1
    await client.table(ids[1], "en")
    assert len(portal.calls) == TABLE_CACHE_SIZE + 2


async def test_a_bad_table_id_or_language_never_reaches_the_api(portal, client):
    with pytest.raises(NotFound, match="not a table id"):
        await client.table("../etc", "en")
    with pytest.raises(NotFound):
        await client.table("", "en")
    with pytest.raises(AzstatError, match="lang must be"):
        await client.table("DT_AA_001", "ru")
    with pytest.raises(AzstatError, match="lang must be"):
        await client.catalogue("ru")
    assert portal.calls == []


async def test_an_unknown_table_is_not_found_and_other_refusals_keep_the_api_message(
    portal, client
):
    with pytest.raises(NotFound, match="no table 'DT_ZZ_999'"):
        await client.table("DT_ZZ_999", "en")
    refusal = httpx.Response(400, json={"success": False, "message": "Xəta baş verdi."})
    with pytest.raises(AzstatError, match="rejected data: Xəta baş verdi"):
        await make_client(lambda request: refusal).table("DT_ZZ_999", "en")
    assert len(portal.calls) == 1


@pytest.mark.parametrize("status", [403, 429])
async def test_a_refusal_is_reported_and_never_retried(status):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(status)

    with pytest.raises(EndpointBlocked, match=f"HTTP {status}"):
        await make_client(handler).catalogue("en")
    assert len(calls) == 1


async def test_one_retry_on_a_server_error(portal):
    answers = [httpx.Response(503), None]

    def handler(request):
        return answers.pop(0) or portal.handle(request)

    table = await make_client(handler).table("DT_AA_001", "en")
    assert table.table_id == "DT_AA_001"
    assert answers == []


async def test_one_retry_on_a_network_error(portal):
    failures = [httpx.ConnectError("boom")]

    def handler(request):
        if failures:
            raise failures.pop()
        return portal.handle(request)

    assert len(await make_client(handler).catalogue("en")) == 39
    assert failures == []


async def test_gives_up_after_the_second_failure():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(503)

    with pytest.raises(AzstatError, match=r"did not answer data.*503"):
        await make_client(handler).table("DT_AA_001", "en")
    assert len(calls) == 2


@pytest.mark.parametrize("failure", [httpx.DecodingError("bad gzip"), httpx.InvalidURL("bad")])
async def test_an_undecodable_answer_is_an_api_error(failure):
    def handler(request):
        raise failure

    with pytest.raises(AzstatError, match="did not answer data"):
        await make_client(handler).table("DT_AA_001", "en")


@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (httpx.Response(200, text="<html>maintenance</html>"), AzstatError, "not JSON"),
        (httpx.Response(200, json=[]), UnexpectedShape, "not a JSON object"),
        (httpx.Response(200, json={"success": False}), AzstatError, "rejected data: HTTP 200"),
        (httpx.Response(200, json={"success": True, "table": {}}), UnexpectedShape, "no 'table'"),
    ],
)
async def test_unexpected_answers_become_errors(response, error, message):
    with pytest.raises(error, match=message):
        await make_client(lambda request: response).table("DT_AA_001", "en")


async def test_a_catalogue_in_another_shape_fails_loudly():
    answer = httpx.Response(200, json={"success": True, "message": "ok"})
    with pytest.raises(UnexpectedShape, match="no 'data' list"):
        await make_client(lambda request: answer).catalogue("en")


async def test_redirects_are_not_followed():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"location": "https://elsewhere.example/data"})

    with pytest.raises(AzstatError, match="redirected data"):
        await make_client(handler).table("DT_AA_001", "en")
    assert [u.host for u in calls] == ["www.azstat.gov.az"]


async def test_a_declared_size_over_the_limit_is_refused_without_reading():
    def handler(request):
        return httpx.Response(200, headers={"content-length": "5000"}, content=b"{}")

    with pytest.raises(TableTooLarge, match="5,000 bytes; this server reads at most 1,000 bytes"):
        await make_client(handler, max_bytes=1000).table("DT_AA_001", "en")


async def test_a_stream_that_outgrows_the_limit_is_cut_off():
    async def body():
        for _ in range(10):
            yield b" " * 200

    client = make_client(lambda request: httpx.Response(200, content=body()), max_bytes=1000)
    with pytest.raises(TableTooLarge, match="larger than the 1,000 bytes"):
        await client.table("DT_AA_001", "en")


async def test_an_answer_exactly_at_the_limit_is_read():
    raw = json.dumps({"success": True, "table": {"table_id": "T", "table_name": "N"}, "data": []})

    def answer(request):
        return httpx.Response(200, content=raw.encode())

    table = await make_client(answer, max_bytes=len(raw)).table("DT_AA_001", "en")
    assert table.rows == ()
    with pytest.raises(TableTooLarge):
        await make_client(answer, max_bytes=len(raw) - 1).table("DT_AA_001", "en")


async def test_the_default_limit_is_twenty_megabytes():
    def handler(request):
        return httpx.Response(200, headers={"content-length": str(21 * 1024 * 1024)}, content=b"{}")

    with pytest.raises(TableTooLarge, match="reads at most 20 MB"):
        await make_client(handler).table("DT_AA_001", "en")


async def test_the_catalogue_has_its_own_limit(monkeypatch, client):
    monkeypatch.setattr(client_module, "MAX_CATALOGUE_BYTES", 100)
    with pytest.raises(TableTooLarge):
        await client.catalogue("en")


async def test_the_default_http_client_names_itself_and_does_not_follow_redirects(
    portal, monkeypatch
):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(portal.handle), **kw)
    )
    seen = []

    def spy(request):
        seen.append(request.headers["user-agent"])
        if request.url.path.endswith("/data") and request.url.params["table_id"] == "DT_GO_001":
            return httpx.Response(302, headers={"location": "https://elsewhere.example/"})

    portal.override = spy
    client = AzstatClient(min_interval=0)
    await client.catalogue("en")
    await client.table("DT_AA_001", "en")
    with pytest.raises(AzstatError, match="redirected"):
        await client.table("DT_GO_001", "en")
    await client.aclose()
    assert set(seen) == {f"azerbaijan-mcp-azstat/{__version__}"}
    assert {u.host for u in portal.calls} == {"www.azstat.gov.az"}


async def test_requests_to_the_host_are_spaced_one_second_apart(portal, load):
    serve_any_table(portal, load)
    clock = Clock()
    client = AzstatClient(http=portal.http, now=clock.time, sleep=clock.sleep, retry_delay=0)
    for table_id in ("DT_A_001", "DT_A_002", "DT_A_003"):
        await client.table(table_id, "en")
    assert clock.slept == [1.0, 1.0]


def test_the_api_base_comes_from_the_environment(monkeypatch):
    monkeypatch.delenv("AZSTAT_API_BASE", raising=False)
    assert AzstatClient.from_env()._api_base == "https://www.azstat.gov.az/AsisOpenDataApi"
    monkeypatch.setenv("AZSTAT_API_BASE", "https://mirror.example/api/")
    assert AzstatClient.from_env()._api_base == "https://mirror.example/api"


def test_the_api_base_must_be_https():
    with pytest.raises(ValueError, match="https://"):
        AzstatClient(api_base="http://www.azstat.gov.az/AsisOpenDataApi")


async def test_a_client_that_was_handed_in_is_not_closed_by_aclose(portal):
    http = portal.http
    await AzstatClient(http=http).aclose()
    assert not http.is_closed
