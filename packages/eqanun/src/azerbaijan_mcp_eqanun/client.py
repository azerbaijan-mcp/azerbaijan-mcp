"""HTTP access to e-qanun.az: its search API and the act files that API points to.

The API at api.e-qanun.az has no public documentation and the site publishes no terms or robots.txt,
so this client keeps to the manners of a considerate reader: an honest User-Agent that names this
project, at most one request a second to each host, answers kept in memory, a ceiling on the size
of a file, and a full stop on HTTP 403 and 429.
"""

import asyncio
import datetime as dt
import json
import os
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar
from urllib.parse import urlsplit

import httpx

from . import __version__
from .acts import ParsedAct, parse_act
from .errors import EndpointBlocked, EqanunError, NotFound, TooLarge, UnexpectedShape
from .listing import (
    STATUS_IDS,
    ActMeta,
    ActSummary,
    TypeNode,
    Version,
    file_path,
    parse_framework,
    parse_search,
    parse_types,
    parse_versions,
)

DEFAULT_API_BASE = "https://api.e-qanun.az"
DEFAULT_FILES_BASE = "https://frameworks.e-qanun.az"
PROJECT_URL = "https://github.com/azerbaijan-mcp/azerbaijan-mcp"
MAX_ACT_BYTES = 30 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
SEARCH_TTL = 600.0
STABLE_TTL = 3600.0
SEARCH_CACHE_SIZE = 32
LISTING_CACHE_SIZE = 64
ACT_CACHE_SIZE = 4
RETRY_DELAY = 0.5
BLOCKED_CODES = {403, 429}
NETWORK_ERRORS = (httpx.RequestError, httpx.InvalidURL)
T = TypeVar("T")
SearchField = Literal["title", "text"]
StatusFilter = Literal["in_force", "repealed", "all"]
Found = tuple[int, tuple[ActSummary, ...]]


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True, slots=True)
class Fetched(Generic[T]):
    """A value read from the site, with the moment it was read."""

    value: T
    fetched_at: dt.datetime


@dataclass(slots=True)
class _Kept(Generic[T]):
    result: Fetched[T]
    expires: float
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class _Answer:
    status: int
    body: bytes
    etag: str | None
    last_modified: str | None


class _Store(Generic[T]):
    """Answers kept for a while; the one used longest ago goes first when there are too many."""

    def __init__(self, size: int, ttl: float, now: Callable[[], float]) -> None:
        self._items: OrderedDict[Any, _Kept[T]] = OrderedDict()
        self._size, self._ttl, self._now = size, ttl, now

    def get(self, key: Any) -> _Kept[T] | None:
        kept = self._items.get(key)
        if kept is not None:
            self._items.move_to_end(key)
        return kept

    def fresh(self, kept: _Kept[T]) -> bool:
        return kept.expires > self._now()

    def put(self, key: Any, result: Fetched[T], **validators: str | None) -> Fetched[T]:
        self._items[key] = _Kept(result, self._now() + self._ttl, **validators)
        self._items.move_to_end(key)
        while len(self._items) > self._size:
            self._items.popitem(last=False)
        return result

    def renew(self, kept: _Kept[T], fetched_at: dt.datetime) -> Fetched[T]:
        kept.result = Fetched(kept.result.value, fetched_at)
        kept.expires = self._now() + self._ttl
        return kept.result


class EqanunClient:
    """Async client for acts and their files, with caches and a request limit per host."""

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        *,
        api_base: str = DEFAULT_API_BASE,
        files_base: str = DEFAULT_FILES_BASE,
        max_bytes: int = MAX_ACT_BYTES,
        min_interval: float = 1.0,
        retry_delay: float = RETRY_DELAY,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], dt.datetime] = _utc_now,
    ) -> None:
        if not (api_base.startswith("https://") and files_base.startswith("https://")):
            raise ValueError("The base URLs must start with https://")
        self._http = http
        self._owns_http = http is None
        self._api_base = api_base.rstrip("/")
        self._files_base = files_base.rstrip("/")
        self._max_bytes = max_bytes
        self._min_interval = min_interval
        self._retry_delay = retry_delay
        self._now = now
        self._sleep = sleep
        self._clock = clock
        self._searches: _Store[Found] = _Store(SEARCH_CACHE_SIZE, SEARCH_TTL, now)
        self._types: _Store[tuple[TypeNode, ...]] = _Store(1, STABLE_TTL, now)
        self._metas: _Store[ActMeta] = _Store(LISTING_CACHE_SIZE, STABLE_TTL, now)
        self._versions: _Store[tuple[Version, ...]] = _Store(LISTING_CACHE_SIZE, STABLE_TTL, now)
        self._acts: _Store[ParsedAct] = _Store(ACT_CACHE_SIZE, STABLE_TTL, now)
        self._last_request: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._act_locks: dict[int, asyncio.Lock] = {}

    @classmethod
    def from_env(cls) -> "EqanunClient":
        """Read EQANUN_API_BASE and EQANUN_FILES_BASE, if set."""
        return cls(
            api_base=os.environ.get("EQANUN_API_BASE", DEFAULT_API_BASE),
            files_base=os.environ.get("EQANUN_FILES_BASE", DEFAULT_FILES_BASE),
        )

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                follow_redirects=False,
                headers={
                    "User-Agent": f"azerbaijan-mcp-eqanun/{__version__} (+{PROJECT_URL})",
                    "Accept-Language": "AZ",
                },
            )
        return self._http

    async def _throttle(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = (
                self._last_request.get(host, -self._min_interval) + self._min_interval - self._now()
            )
            if wait > 0:
                await self._sleep(wait)
            self._last_request[host] = self._now()

    async def search(
        self,
        query: str,
        *,
        field: SearchField = "title",
        status: StatusFilter = "in_force",
        type_ids: tuple[int, ...] = (),
        exact: bool = False,
        start: int = 0,
        length: int = 20,
    ) -> Fetched[Found]:
        """Acts whose title (or text) has the words, newest first. Without words: all acts."""
        key = (query, field, status, tuple(sorted(type_ids)), exact, start, length)

        async def load() -> Found:
            params = {
                "start": str(start),
                "length": str(length),
                "orderColumn": "8",
                "orderDirection": "desc",
                "name": query,
                "title": "true" if field == "title" else "false",
                "text": "true" if field == "text" else "false",
                "exact": "true" if exact else "false",
                "codeType": "1",
                "dateType": "1",
                "statusId": str(STATUS_IDS[status]),
                "secondType": "2",
                "specialDate": "false",
                "array": ",".join(str(number) for number in sorted(type_ids)),
            }
            total, rows = parse_search(
                await self._api("getDetailSearch", params, what="the search")
            )
            return total, tuple(rows)

        return await self._cached(self._searches, key, load)

    async def types(self) -> Fetched[tuple[TypeNode, ...]]:
        """The kinds of act (laws, decrees, decisions and so on), as a tree."""

        async def load() -> tuple[TypeNode, ...]:
            return parse_types(await self._api("all-type", what="the list of act types"))

        return await self._cached(self._types, "all", load)

    async def framework(self, act_id: int) -> Fetched[ActMeta]:
        """An act's requisites: title, type, status, dates, publications and its file's address."""

        async def load() -> ActMeta:
            body = await self._api(
                f"framework/{act_id}", what=f"act {act_id}", missing=(400, 404, 500)
            )
            return parse_framework(body)

        return await self._cached(self._metas, act_id, load)

    async def versions(self, act_id: int) -> Fetched[tuple[Version, ...]]:
        """The editions of an act, newest first, each with the date it took effect."""

        async def load() -> tuple[Version, ...]:
            params = {"id": str(act_id)}
            body = await self._api("getVersions", params, what=f"the editions of act {act_id}")
            return parse_versions(body)

        return await self._cached(self._versions, act_id, load)

    async def act(self, act_id: int) -> Fetched[ParsedAct]:
        """An act's file, read and parsed. A kept copy is asked about, not downloaded again."""
        async with self._act_locks.setdefault(act_id, asyncio.Lock()):
            kept = self._acts.get(act_id)
            if kept is not None and self._acts.fresh(kept):
                return kept.result
            meta = (await self.framework(act_id)).value
            url = f"{self._files_base}/{file_path(meta.html_url)}"
            headers = {}
            if kept is not None and kept.etag:
                headers["If-None-Match"] = kept.etag
            if kept is not None and kept.last_modified:
                headers["If-Modified-Since"] = kept.last_modified
            answer = await self._fetch(url, None, self._max_bytes, headers=headers or None)
            if answer.status == 304 and kept is not None:
                return self._acts.renew(kept, self._clock())
            if answer.status in (404, 410):
                raise NotFound(f"e-qanun.az has no file for act {act_id} (HTTP {answer.status}).")
            if answer.status != 200:
                raise EqanunError(f"The file of act {act_id} answered HTTP {answer.status}.")
            parsed = await asyncio.to_thread(parse_act, answer.body)
            return self._acts.put(
                act_id,
                Fetched(parsed, self._clock()),
                etag=answer.etag,
                last_modified=answer.last_modified,
            )

    async def _cached(
        self, store: _Store[T], key: Any, load: Callable[[], Awaitable[T]]
    ) -> Fetched[T]:
        kept = store.get(key)
        if kept is not None and store.fresh(kept):
            return kept.result
        return store.put(key, Fetched(await load(), self._clock()))

    async def _api(
        self,
        path: str,
        params: dict[str, str] | None = None,
        *,
        what: str,
        missing: tuple[int, ...] = (),
    ) -> Any:
        answer = await self._fetch(
            f"{self._api_base}/{path}", params, MAX_JSON_BYTES, final=missing
        )
        if answer.status in missing:
            raise NotFound(f"e-qanun.az has no {what} (HTTP {answer.status}).")
        if answer.status != 200:
            raise EqanunError(f"e-qanun.az rejected the request for {what} (HTTP {answer.status}).")
        try:
            return json.loads(answer.body)
        except (ValueError, RecursionError) as exc:
            raise UnexpectedShape(f"The answer about {what} is not JSON.") from exc

    async def _fetch(
        self,
        url: str,
        params: dict[str, str] | None,
        cap: int,
        *,
        headers: dict[str, str] | None = None,
        final: tuple[int, ...] = (),
    ) -> _Answer:
        """One GET, tried twice at most. Statuses below 500, and those in final, are returned."""
        host = urlsplit(url).hostname or ""
        error: Exception
        for attempt in (1, 2):
            await self._throttle(host)
            try:
                async with self._client().stream(
                    "GET", url, params=params, headers=headers
                ) as response:
                    status = response.status_code
                    if status in BLOCKED_CODES:
                        raise EndpointBlocked(
                            f"e-qanun.az refuses requests to {host} (HTTP {status}). "
                            "This server does not retry or work around it."
                        )
                    if 300 <= status < 400 and status != 304:
                        raise EqanunError(
                            f"{host} redirected a request; redirects are not followed."
                        )
                    if status < 500 or status in final:
                        return _Answer(
                            status,
                            await self._read(response, cap),
                            response.headers.get("etag"),
                            response.headers.get("last-modified"),
                        )
                    error = EqanunError(f"HTTP {status}")
            except NETWORK_ERRORS as exc:
                error = exc
            if attempt == 2:
                raise EqanunError(f"e-qanun.az did not answer ({host}): {error}") from error
            await self._sleep(self._retry_delay)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _read(self, response: httpx.Response, cap: int) -> bytes:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cap:
            raise TooLarge(self._too_large(cap, int(declared)))
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > cap:
                raise TooLarge(self._too_large(cap))
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _too_large(cap: int, size: int | None = None) -> str:
        megabytes = cap / (1024 * 1024)
        limit = f"{megabytes:g} MB" if megabytes >= 1 else f"{cap:,} bytes"
        if size is None:
            return f"The file is larger than the {limit} this server reads."
        return f"The file is {size:,} bytes; this server reads at most {limit}."
