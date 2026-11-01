from datetime import date

import httpx
import pytest

from azerbaijan_mcp_cbar.client import CbarClient, FeedError, RatesUnavailable

pytestmark = pytest.mark.anyio

TODAY = date(2026, 11, 1)


def make_client(http: httpx.AsyncClient, **kwargs) -> CbarClient:
    return CbarClient(http=http, retry_delay=0, today=lambda: TODAY, **kwargs)


async def test_weekend_request_returns_the_last_business_day_sheet(feed):
    sheet = await make_client(feed.http).get_sheet(date(2026, 10, 31))
    assert sheet.sheet_date == date(2026, 10, 30)
    assert feed.calls == ["/currencies/31.10.2026.xml"]


async def test_past_sheets_are_cached_for_good(feed):
    clock = [0.0]
    client = make_client(feed.http, now=lambda: clock[0])
    await client.get_sheet(date(2026, 10, 30))
    clock[0] += 10**9
    await client.get_sheet(date(2026, 10, 30))
    assert len(feed.calls) == 1


async def test_todays_sheet_is_cached_for_a_few_minutes(feed):
    clock = [0.0]
    client = make_client(feed.http, now=lambda: clock[0])
    await client.get_sheet(TODAY)
    clock[0] += 599
    await client.get_sheet(TODAY)
    assert len(feed.calls) == 1
    clock[0] += 2
    await client.get_sheet(TODAY)
    assert len(feed.calls) == 2


async def test_unknown_date_is_unavailable(feed):
    with pytest.raises(RatesUnavailable, match="2026-10-29"):
        await make_client(feed.http).get_sheet(date(2026, 10, 29))


async def test_one_retry_on_server_error(sheet_xml):
    responses = [httpx.Response(503), httpx.Response(200, content=sheet_xml)]
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: responses.pop(0)))
    sheet = await make_client(http).get_sheet(date(2026, 10, 30))
    assert sheet.sheet_date == date(2026, 10, 30)
    assert responses == []


async def test_gives_up_after_the_second_server_error():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(503)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(FeedError, match="503"):
        await make_client(http).get_sheet(date(2026, 10, 30))
    assert len(calls) == 2


async def test_no_retry_on_client_error():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(403)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(FeedError, match="403"):
        await make_client(http).get_sheet(date(2026, 10, 30))
    assert len(calls) == 1
