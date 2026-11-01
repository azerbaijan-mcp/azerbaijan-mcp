import httpx
import pytest

from azerbaijan_mcp_opendata import __version__
from azerbaijan_mcp_opendata.client import (
    MAX_REDIRECTS,
    EndpointBlocked,
    NotFound,
    OpenDataClient,
    PortalError,
    ResourceRefused,
)

pytestmark = pytest.mark.anyio

SORT = "score desc, metadata_modified desc"


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


def make_client(handler, **kwargs) -> OpenDataClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs.setdefault("min_interval", 0)
    kwargs.setdefault("retry_delay", 0)
    return OpenDataClient(http=http, **kwargs)


def ok(result: dict) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "result": result})


async def test_search_sends_the_expected_parameters(portal, client):
    result = await client.search(
        q="population",
        fq=['organization:"dsk"', 'license_id:"cc-zero"'],
        rows=5,
        start=10,
        sort=SORT,
    )
    assert result["count"] == 130
    url = portal.calls[-1]
    assert (url.host, url.path) == ("admin.opendata.az", "/api/3/action/package_search")
    assert dict(url.params) == {
        "q": "population",
        "fq": 'organization:"dsk" license_id:"cc-zero"',
        "rows": "5",
        "start": "10",
        "sort": SORT,
    }


async def test_search_without_text_or_filters_omits_them(portal, client):
    await client.search(q=None, fq=[], rows=10, start=0, sort="metadata_modified desc")
    assert dict(portal.calls[-1].params) == {
        "rows": "10",
        "start": "0",
        "sort": "metadata_modified desc",
    }


async def test_the_default_http_client_names_itself_and_does_not_follow_redirects(
    portal, monkeypatch, ids
):
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(portal.handle), **kw)
    )
    seen = []

    def spy(request):
        seen.append(request.headers["user-agent"])

    portal.override = spy
    client = OpenDataClient(min_interval=0)
    await client.facets()
    url = portal.resource(ids.portal_csv)["url"]
    await client.fetch_resource(url)
    await client.aclose()
    assert set(seen) == {f"azerbaijan-mcp-opendata/{__version__}"}
    assert [u.host for u in portal.calls][-2:] == ["admin.opendata.az", "data-storage.opendata.az"]


async def test_searches_are_cached_for_ten_minutes(portal):
    clock = Clock()
    client = OpenDataClient(http=portal.http, min_interval=0, now=clock.time, sleep=clock.sleep)
    args = {"q": "population", "fq": [], "rows": 5, "start": 0, "sort": SORT}
    await client.search(**args)
    await client.search(**args)
    assert len(portal.calls) == 1
    await client.search(**{**args, "start": 5})
    assert len(portal.calls) == 2
    clock.now += 601
    await client.search(**args)
    assert len(portal.calls) == 3


async def test_facets_are_one_request_cached_for_an_hour(portal):
    clock = Clock()
    client = OpenDataClient(http=portal.http, min_interval=0, now=clock.time, sleep=clock.sleep)
    first = await client.facets()
    assert dict(portal.calls[0].params)["rows"] == "0"
    assert "organization" in first["search_facets"]
    clock.now += 3599
    await client.facets()
    assert len(portal.calls) == 1
    clock.now += 2
    await client.facets()
    assert len(portal.calls) == 2


async def test_show_returns_the_dataset_and_a_missing_one_is_not_found(portal, client, ids):
    record = await client.show(ids.name)
    assert record["id"] == ids.dataset
    with pytest.raises(NotFound, match="no dataset 'nope'"):
        await client.show("nope")
    with pytest.raises(NotFound):
        await client.show("nope")
    assert [u.params["id"] for u in portal.calls] == [ids.name, "nope", "nope"]


@pytest.mark.parametrize("status", [403, 429])
async def test_a_refusal_is_reported_and_never_retried(status):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(status)

    with pytest.raises(EndpointBlocked, match=f"HTTP {status}"):
        await make_client(handler).facets()
    assert len(calls) == 1


async def test_one_retry_on_a_server_error(portal, ids):
    answers = [httpx.Response(503), None]

    def handler(request):
        return answers.pop(0) or portal.handle(request)

    record = await make_client(handler).show(ids.name)
    assert record["id"] == ids.dataset
    assert answers == []


async def test_one_retry_on_a_network_error(portal):
    failures = [httpx.ConnectError("boom")]

    def handler(request):
        if failures:
            raise failures.pop()
        return portal.handle(request)

    assert (await make_client(handler).facets())["count"] == 2054
    assert failures == []


async def test_gives_up_after_the_second_failure():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(503)

    with pytest.raises(PortalError, match=r"did not answer package_show.*503"):
        await make_client(handler).show("x")
    assert len(calls) == 2


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(200, text="<html>challenge</html>"), "not JSON"),
        (
            httpx.Response(400, json={"success": False, "error": {"message": "Search error"}}),
            "rejected package_search: Search error",
        ),
        (httpx.Response(200, json={"success": False}), "rejected package_search: HTTP 200"),
    ],
)
async def test_unexpected_answers_become_portal_errors(response, message):
    with pytest.raises(PortalError, match=message):
        await make_client(lambda request: response).search(
            q="x", fq=[], rows=1, start=0, sort="score desc"
        )


async def test_requests_to_one_host_are_spaced_one_second_apart(portal):
    clock = Clock()
    client = OpenDataClient(http=portal.http, now=clock.time, sleep=clock.sleep, retry_delay=0)
    for text in ("a", "b", "c"):
        await client.search(q=text, fq=[], rows=1, start=0, sort="score desc")
    assert clock.slept == [1.0, 1.0]
    await client.fetch_resource("https://www.azstat.gov.az/AsisOpenDataApi/csv?table_id=T")
    assert clock.slept == [1.0, 1.0]


def test_the_defaults_come_from_the_environment(monkeypatch):
    monkeypatch.delenv("OPENDATA_AZ_API_BASE", raising=False)
    monkeypatch.delenv("OPENDATA_AZ_RESOURCE_HOSTS", raising=False)
    default = OpenDataClient.from_env()
    assert default.host_allowed("https://opendata.az/a.csv")
    monkeypatch.setenv("OPENDATA_AZ_API_BASE", "https://mirror.example/api/3/action/")
    monkeypatch.setenv("OPENDATA_AZ_RESOURCE_HOSTS", "files.example, Other.example")
    custom = OpenDataClient.from_env()
    assert custom.host_allowed("https://x.files.example/a.csv")
    assert custom.host_allowed("https://other.example/a.csv")
    assert not custom.host_allowed("https://opendata.az/a.csv")


def test_the_api_base_must_be_https():
    with pytest.raises(ValueError, match="https://"):
        OpenDataClient(api_base="http://admin.opendata.az/api/3/action")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://opendata.az/a.csv", True),
        ("https://admin.opendata.az/a.csv", True),
        ("https://data-storage.opendata.az/a.csv", True),
        ("https://www.azstat.gov.az/AsisOpenDataApi/csv?x=1", True),
        ("https://OPENDATA.AZ/a.csv", True),
        ("https://opendata.az:443/a.csv", True),
        ("http://opendata.az/a.csv", False),
        ("https://evilopendata.az/a.csv", False),
        ("https://opendata.az.evil.example/a.csv", False),
        ("https://opendata.az@evil.example/a.csv", False),
        ("https://evil.example/?next=https://opendata.az/", False),
        ("https://opendata.az:8443/a.csv", False),
        ("https://opendata.az:abc/a.csv", False),
        ("ftp://opendata.az/a.csv", False),
        ("file:///etc/passwd", False),
        ("//opendata.az/a.csv", False),
        ("/relative/a.csv", False),
        ("", False),
    ],
)
def test_host_allowed(url, expected):
    assert OpenDataClient().host_allowed(url) is expected


async def test_a_file_is_fetched_through_a_redirect_to_the_storage_host(portal, client, read, ids):
    url = portal.resource(ids.portal_csv)["url"]
    content, content_type = await client.fetch_resource(url)
    assert content == read("portal_style.csv")
    assert content_type == "text/csv"
    assert [u.host for u in portal.calls] == ["admin.opendata.az", "data-storage.opendata.az"]


async def test_a_host_that_is_not_allowed_is_never_contacted(portal, client):
    with pytest.raises(ResourceRefused, match="is not on an allowed https host") as refused:
        await client.fetch_resource("https://example.com/a.csv")
    assert refused.value.status == "link_only"
    assert portal.calls == []


@pytest.mark.parametrize(
    "target",
    ["https://internal.example/secret.csv", "http://data-storage.opendata.az/a.csv"],
)
async def test_every_redirect_is_checked_again(target):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"location": target})

    with pytest.raises(ResourceRefused, match="redirects away from") as refused:
        await make_client(handler).fetch_resource("https://opendata.az/a.csv")
    assert refused.value.status == "link_only"
    assert [u.host for u in calls] == ["opendata.az"]


async def test_a_relative_redirect_stays_on_the_host():
    def handler(request):
        if request.url.path == "/a.csv":
            return httpx.Response(301, headers={"location": "/final.csv"})
        return httpx.Response(200, content=b"a,b\n1,2\n")

    content, _ = await make_client(handler).fetch_resource("https://opendata.az/a.csv")
    assert content == b"a,b\n1,2\n"


async def test_redirect_loops_and_redirects_without_a_target_are_errors():
    calls = []

    def loop(request):
        calls.append(request.url)
        return httpx.Response(302, headers={"location": "https://opendata.az/again.csv"})

    with pytest.raises(PortalError, match="too many times"):
        await make_client(loop).fetch_resource("https://opendata.az/a.csv")
    assert len(calls) == MAX_REDIRECTS + 1
    with pytest.raises(PortalError, match="without a target"):
        await make_client(lambda request: httpx.Response(302)).fetch_resource(
            "https://opendata.az/a.csv"
        )


async def test_a_declared_size_over_the_limit_is_refused_without_reading():
    def handler(request):
        return httpx.Response(200, headers={"content-length": "5000"}, content=b"x")

    client = make_client(handler, max_bytes=1000)
    with pytest.raises(ResourceRefused, match="5,000 bytes; the preview limit is 1,000 bytes") as r:
        await client.fetch_resource("https://opendata.az/a.csv")
    assert r.value.status == "too_large"


async def test_a_stream_that_outgrows_the_limit_is_cut_off():
    async def body():
        for _ in range(10):
            yield b"x" * 200

    client = make_client(lambda request: httpx.Response(200, content=body()), max_bytes=1000)
    with pytest.raises(ResourceRefused, match="larger than the 1,000 bytes") as refused:
        await client.fetch_resource("https://opendata.az/a.csv")
    assert refused.value.status == "too_large"


async def test_a_file_exactly_at_the_limit_is_read():
    client = make_client(lambda request: httpx.Response(200, content=b"x" * 1000), max_bytes=1000)
    content, _ = await client.fetch_resource("https://opendata.az/a.csv")
    assert len(content) == 1000


async def test_the_default_limit_is_five_megabytes():
    def handler(request):
        return httpx.Response(200, headers={"content-length": str(6 * 1024 * 1024)}, content=b"x")

    with pytest.raises(ResourceRefused, match="preview limit is 5 MB"):
        await make_client(handler).fetch_resource("https://opendata.az/a.csv")


@pytest.mark.parametrize(
    ("status", "error", "message"),
    [(404, NotFound, "gone"), (403, PortalError, "HTTP 403"), (500, PortalError, "HTTP 500")],
)
async def test_file_errors_are_reported_and_not_retried(status, error, message):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(status)

    with pytest.raises(error, match=message):
        await make_client(handler).fetch_resource("https://opendata.az/a.csv")
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure", [httpx.ReadTimeout("slow"), httpx.DecodingError("bad gzip"), httpx.InvalidURL("bad")]
)
async def test_a_network_error_while_fetching_a_file(failure):
    def handler(request):
        raise failure

    with pytest.raises(PortalError, match=type(failure).__name__):
        await make_client(handler).fetch_resource("https://opendata.az/a.csv")


async def test_an_undecodable_portal_answer_is_a_portal_error():
    def handler(request):
        raise httpx.DecodingError("bad gzip")

    with pytest.raises(PortalError, match="did not answer package_show"):
        await make_client(handler).show("x")


async def test_a_client_that_was_handed_in_is_not_closed_by_aclose(portal):
    http = portal.http
    await OpenDataClient(http=http).aclose()
    assert not http.is_closed
