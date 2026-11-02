import asyncio
import datetime as dt

import httpx
import pytest

from azerbaijan_mcp_eqanun import __version__
from azerbaijan_mcp_eqanun.client import ACT_CACHE_SIZE, MAX_ACT_BYTES, EqanunClient
from azerbaijan_mcp_eqanun.errors import (
    EndpointBlocked,
    EqanunError,
    NotFound,
    TooLarge,
    UnexpectedShape,
)

pytestmark = pytest.mark.anyio

EPOCH = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.UTC)


class Clock:
    """A fake clock whose sleep moves time forward and remembers how long it was asked to wait."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    def utc(self) -> dt.datetime:
        return EPOCH + dt.timedelta(seconds=self.now)

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def timed(site, clock, **kwargs) -> EqanunClient:
    kwargs.setdefault("min_interval", 0)
    return EqanunClient(
        http=site.http, now=clock.time, sleep=clock.sleep, clock=clock.utc, **kwargs
    )


def make_client(handler, **kwargs) -> EqanunClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    kwargs.setdefault("min_interval", 0)
    kwargs.setdefault("retry_delay", 0)
    return EqanunClient(http=http, **kwargs)


def chunked(*chunks: bytes) -> httpx.Response:
    """An answer that does not say how long it is, so that only reading it shows its size."""

    async def body():
        for chunk in chunks:
            yield chunk

    return httpx.Response(200, content=body())


async def test_a_title_search_asks_the_way_the_sites_own_page_does(client, site):
    found = await client.search("mülki məcəllə")
    total, acts = found.value
    assert (total, len(acts)) == (633, 3)
    [url] = site.api_calls("/getDetailSearch")
    assert url.host == "api.e-qanun.az"
    assert dict(url.params) == {
        "start": "0",
        "length": "20",
        "orderColumn": "8",
        "orderDirection": "desc",
        "name": "mülki məcəllə",
        "title": "true",
        "text": "false",
        "exact": "false",
        "codeType": "1",
        "dateType": "1",
        "statusId": "1",
        "secondType": "2",
        "specialDate": "false",
        "array": "",
    }


@pytest.mark.parametrize(
    ("options", "sent"),
    [
        ({"field": "text"}, {"title": "false", "text": "true"}),
        ({"status": "repealed"}, {"statusId": "2"}),
        ({"status": "all"}, {"statusId": "0"}),
        ({"status": "in_force"}, {"statusId": "1"}),
        ({"exact": True}, {"exact": "true"}),
        ({"type_ids": (107, 28, 30)}, {"array": "28,30,107"}),
        ({"start": 40, "length": 5}, {"start": "40", "length": "5"}),
    ],
)
async def test_the_options_of_a_search_become_the_sites_parameters(client, site, options, sent):
    await client.search("x", **options)
    [url] = site.api_calls("/getDetailSearch")
    assert {name: url.params[name] for name in sent} == sent


async def test_a_search_without_words_lists_acts(client, site):
    await client.search("", type_ids=(107,))
    [url] = site.api_calls("/getDetailSearch")
    assert (url.params["name"], url.params["array"]) == ("", "107")


async def test_the_site_is_told_who_is_asking_and_in_which_language():
    client = EqanunClient()
    headers = client._client().headers
    assert headers["user-agent"] == (
        f"azerbaijan-mcp-eqanun/{__version__} (+https://github.com/azerbaijan-mcp/azerbaijan-mcp)"
    )
    assert headers["accept-language"] == "AZ"
    await client.aclose()


async def test_a_search_is_kept_for_ten_minutes_and_only_for_the_same_question(site):
    clock = Clock()
    client = timed(site, clock)
    first = await client.search("mülki")
    assert (await client.search("mülki")).fetched_at == first.fetched_at
    assert len(site.api_calls("/getDetailSearch")) == 1
    await client.search("mülki", start=20)
    await client.search("mülki", field="text")
    await client.search("mülki", status="all")
    assert len(site.api_calls("/getDetailSearch")) == 4
    clock.now += 599
    await client.search("mülki")
    assert len(site.api_calls("/getDetailSearch")) == 4
    clock.now += 2
    again = await client.search("mülki")
    assert len(site.api_calls("/getDetailSearch")) == 5
    assert again.fetched_at == EPOCH + dt.timedelta(seconds=601)


async def test_the_kinds_of_act_are_read_once_an_hour(site):
    clock = Clock()
    client = timed(site, clock)
    nodes = (await client.types()).value
    assert len(nodes) == 81
    await client.types()
    clock.now += 3599
    await client.types()
    assert len(site.api_calls("/all-type")) == 1
    clock.now += 2
    await client.types()
    assert len(site.api_calls("/all-type")) == 2


async def test_an_acts_requisites_and_editions_are_read_once_an_hour(site):
    clock = Clock()
    client = timed(site, clock)
    meta = (await client.framework(46944)).value
    versions = (await client.versions(46944)).value
    assert meta.summary.title == "Azərbaycan Respublikasının Mülki Məcəlləsi"
    assert [v.effective_date for v in versions] == ["2026-07-14", "2026-05-26", "2026-02-27"]
    [versions_url] = site.api_calls("/getVersions")
    assert versions_url.params["id"] == "46944"
    await client.framework(46944)
    await client.versions(46944)
    assert len(site.api_calls()) == 2
    clock.now += 3601
    await client.framework(46944)
    assert len(site.api_calls("/framework/46944")) == 2


async def test_an_act_with_no_editions_has_an_empty_list(client):
    assert (await client.versions(41807)).value == ()


async def test_an_act_the_site_does_not_know_is_not_found_after_one_request(client, site):
    # the API answers HTTP 500 for an id it has no act for
    with pytest.raises(NotFound, match=r"no act 999999999 \(HTTP 500\)"):
        await client.framework(999999999)
    assert len(site.api_calls()) == 1
    with pytest.raises(NotFound):
        await client.act(999999999)
    assert site.file_calls() == []


async def test_an_acts_file_is_read_from_the_files_host_and_parsed(client, site):
    fetched = await client.act(46944)
    assert [article.number for article in fetched.value.articles] == ["1", "2", "6", "13", "14"]
    [file] = site.calls[-1:]
    assert (file.url.host, file.url.path) == ("frameworks.e-qanun.az", "/46/f_46944.html")
    assert "if-none-match" not in file.headers
    # the address the API gives is on the main host, which turns plain clients away
    assert {call.url.host for call in site.calls} == {"api.e-qanun.az", "frameworks.e-qanun.az"}


async def test_the_time_an_act_was_read_is_kept_with_it(site):
    clock = Clock()
    client = timed(site, clock)
    fetched = await client.act(46944)
    assert fetched.fetched_at == EPOCH
    clock.now += 100
    assert (await client.act(46944)).fetched_at == EPOCH


async def test_an_act_asked_for_twice_at_once_is_read_once(client, site):
    first, second = await asyncio.gather(client.act(46944), client.act(46944))
    assert first.value is second.value
    assert len(site.file_calls()) == 1


async def test_a_kept_act_is_asked_about_after_an_hour_not_downloaded_again(site):
    clock = Clock()
    client = timed(site, clock)
    first = await client.act(46944)
    clock.now += 3599
    assert (await client.act(46944)).value is first.value
    assert len(site.file_calls()) == 1
    clock.now += 2
    second = await client.act(46944)
    assert len(site.file_calls()) == 2
    asked = site.calls[-1]
    assert asked.headers["if-none-match"] == site.etag
    assert asked.headers["if-modified-since"] == site.modified
    assert second.value is first.value  # "not modified": nothing was parsed again
    assert second.fetched_at == EPOCH + dt.timedelta(seconds=3601)
    await client.act(46944)
    assert len(site.file_calls()) == 2  # and it is good for another hour


async def test_a_changed_act_is_read_again_when_the_site_says_so(site):
    clock = Clock()
    client = timed(site, clock)
    first = await client.act(46944)
    site.files["46/f_46944.html"] = "act_decree.html"
    site.etag = '"changed"'
    clock.now += 3601
    second = await client.act(46944)
    assert second.value is not first.value
    assert second.value.articles == ()
    assert site.calls[-1].headers["if-none-match"] != '"changed"'


async def test_only_the_latest_acts_are_kept(site):
    for number in range(1, ACT_CACHE_SIZE + 2):
        site.frameworks[number] = "framework_decree.json"
    client = EqanunClient(http=site.http, min_interval=0)
    for number in range(1, ACT_CACHE_SIZE + 2):
        await client.act(number)
    assert len(site.file_calls()) == ACT_CACHE_SIZE + 1
    await client.act(ACT_CACHE_SIZE + 1)
    assert len(site.file_calls()) == ACT_CACHE_SIZE + 1
    await client.act(1)  # the first one was dropped to make room
    assert len(site.file_calls()) == ACT_CACHE_SIZE + 2


async def test_a_file_that_is_too_big_is_refused_by_its_declared_size(site):
    client = EqanunClient(http=site.http, min_interval=0, max_bytes=1000)
    with pytest.raises(TooLarge, match=r"is [\d,]+ bytes; this server reads at most 1,000 bytes"):
        await client.act(46944)


async def test_a_file_that_is_too_big_is_refused_while_it_is_read():
    def handler(request):
        if request.url.host == "api.e-qanun.az":
            return httpx.Response(200, json=_framework())
        return chunked(b"x" * 60, b"x" * 60, b"x" * 60)

    client = make_client(handler, max_bytes=100)
    with pytest.raises(TooLarge, match="larger than the 100 bytes"):
        await client.act(1)


def _framework():
    return {
        "data": {
            "id": 1,
            "requisite": {"title": "An act", "statusName": "Qüvvədədir"},
            "htmlUrl": "https://e-qanun.az/frameworks/0/f_1.html",
        }
    }


def test_the_default_ceiling_is_thirty_megabytes():
    assert MAX_ACT_BYTES == 30 * 1024 * 1024


@pytest.mark.parametrize("status", [403, 429])
@pytest.mark.parametrize("host", ["api.e-qanun.az", "frameworks.e-qanun.az"])
async def test_a_refusal_stops_everything_and_is_not_retried_or_worked_around(host, status):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == host:
            return httpx.Response(status, text="no")
        return httpx.Response(200, json=_framework())

    client = make_client(handler)
    with pytest.raises(EndpointBlocked, match=rf"refuses requests to {host} \(HTTP {status}\)"):
        if host.startswith("api"):
            await client.types()
        else:
            await client.act(1)
    assert [call.url.host for call in calls].count(host) == 1


async def test_a_server_error_is_tried_once_more_after_a_pause():
    answers = iter([httpx.Response(503), httpx.Response(200, json={"data": []})])
    clock = Clock()
    client = make_client(
        lambda request: next(answers), now=clock.time, sleep=clock.sleep, retry_delay=0.5
    )
    assert (await client.versions(1)).value == ()
    assert clock.slept == [0.5]


async def test_a_server_that_keeps_failing_is_reported_after_two_tries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(502)

    with pytest.raises(EqanunError, match="did not answer"):
        await make_client(handler).types()
    assert len(calls) == 2


async def test_a_dropped_connection_is_tried_once_more():
    answers = [httpx.ConnectError("reset"), httpx.Response(200, json={"data": []})]

    def handler(request):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    assert (await make_client(handler).versions(1)).value == ()
    assert answers == []


async def test_a_redirect_is_not_followed():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(301, headers={"location": "https://elsewhere.example/"})

    with pytest.raises(EqanunError, match="redirected"):
        await make_client(handler).types()
    assert len(calls) == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>maintenance</html>"),
        httpx.Response(200, json={"data": 5}),
        httpx.Response(200, json=[]),
    ],
)
async def test_an_answer_that_is_not_the_expected_shape_is_reported(response):
    with pytest.raises(UnexpectedShape):
        await make_client(lambda request: response).types()


async def test_a_client_error_that_is_not_not_found_is_reported_with_its_status():
    client = make_client(lambda request: httpx.Response(418))
    with pytest.raises(EqanunError, match=r"HTTP 418"):
        await client.types()


async def test_a_file_answered_with_something_else_is_reported(site):
    site.override = lambda request: (
        httpx.Response(418) if request.url.host == "frameworks.e-qanun.az" else None
    )
    client = EqanunClient(http=site.http, min_interval=0)
    with pytest.raises(EqanunError, match=r"file of act 46944 answered HTTP 418"):
        await client.act(46944)


async def test_a_file_the_site_does_not_have_is_not_found(site):
    site.files.clear()
    client = EqanunClient(http=site.http, min_interval=0)
    with pytest.raises(NotFound, match=r"no file for act 46944 \(HTTP 404\)"):
        await client.act(46944)


async def test_an_address_the_api_gives_off_the_site_is_never_requested(site):
    def override(request):
        if request.url.path == "/framework/46944":
            body = _framework()
            body["data"]["htmlUrl"] = "https://evil.example/frameworks/46/f_46944.html"
            return httpx.Response(200, json=body)

    site.override = override
    client = EqanunClient(http=site.http, min_interval=0)
    with pytest.raises(UnexpectedShape, match="not one this server reads"):
        await client.act(46944)
    assert all(call.url.host != "evil.example" for call in site.calls)
    assert site.file_calls() == []


async def test_requests_to_one_host_are_a_second_apart_but_hosts_do_not_wait_for_each_other(site):
    clock = Clock()
    client = EqanunClient(http=site.http, now=clock.time, sleep=clock.sleep)
    await client.types()  # the first request to the API: no wait
    await client.versions(1)  # the second: a second after the first
    assert clock.slept == [1.0]
    await client.act(46944)  # the requisites come from the API, and wait; the file does not
    assert clock.slept == [1.0, 1.0]


def test_the_base_addresses_must_be_secure():
    with pytest.raises(ValueError, match="https://"):
        EqanunClient(api_base="http://api.e-qanun.az")
    with pytest.raises(ValueError, match="https://"):
        EqanunClient(files_base="ftp://frameworks.e-qanun.az")


def test_the_base_addresses_can_be_set_in_the_environment(monkeypatch):
    monkeypatch.setenv("EQANUN_API_BASE", "https://api.example.test/v1/")
    monkeypatch.setenv("EQANUN_FILES_BASE", "https://files.example.test")
    client = EqanunClient.from_env()
    assert (client._api_base, client._files_base) == (
        "https://api.example.test/v1",
        "https://files.example.test",
    )
    monkeypatch.delenv("EQANUN_API_BASE")
    monkeypatch.delenv("EQANUN_FILES_BASE")
    client = EqanunClient.from_env()
    assert (client._api_base, client._files_base) == (
        "https://api.e-qanun.az",
        "https://frameworks.e-qanun.az",
    )
