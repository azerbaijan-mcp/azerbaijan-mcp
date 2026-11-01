"""HTTP access to the State Statistical Committee's open data API."""

import asyncio
import json
import os
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from . import __version__
from .catalogue import Entry, parse_catalogue
from .errors import AzstatError, EndpointBlocked, NotFound, TableTooLarge, UnexpectedShape
from .tables import Table, parse_table

DEFAULT_API_BASE = "https://www.azstat.gov.az/AsisOpenDataApi"
LANGS = ("en", "az")
MAX_TABLE_BYTES = 20 * 1024 * 1024
MAX_CATALOGUE_BYTES = 8 * 1024 * 1024
CATALOGUE_TTL = 3600.0
TABLE_TTL = 1800.0
TABLE_CACHE_SIZE = 6
RETRY_DELAY = 0.5
BLOCKED_CODES = {403, 429}
NETWORK_ERRORS = (httpx.RequestError, httpx.InvalidURL)
TABLE_ID = re.compile(r"[A-Za-z0-9_]{1,40}")


class AzstatClient:
    """Async client for the table catalogue and table data, with a cache and a request limit."""

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        *,
        api_base: str = DEFAULT_API_BASE,
        max_bytes: int = MAX_TABLE_BYTES,
        min_interval: float = 1.0,
        retry_delay: float = RETRY_DELAY,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not api_base.startswith("https://"):
            raise ValueError("The API base URL must start with https://")
        self._http = http
        self._owns_http = http is None
        self._api_base = api_base.rstrip("/")
        self._max_bytes = max_bytes
        self._min_interval = min_interval
        self._retry_delay = retry_delay
        self._now = now
        self._sleep = sleep
        self._catalogues: dict[str, tuple[float, tuple[Entry, ...]]] = {}
        self._tables: OrderedDict[tuple[str, str], tuple[float, Table]] = OrderedDict()
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def from_env(cls) -> "AzstatClient":
        """Read AZSTAT_API_BASE, if set."""
        return cls(api_base=os.environ.get("AZSTAT_API_BASE", DEFAULT_API_BASE))

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(60.0, connect=10.0),
                follow_redirects=False,
                headers={"User-Agent": f"azerbaijan-mcp-azstat/{__version__}"},
            )
        return self._http

    async def _throttle(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = (
                self._last_request.get(host, -self._min_interval) + self._min_interval - self._now()
            )
            if wait > 0:
                await self._sleep(wait)
            self._last_request[host] = self._now()

    async def catalogue(self, lang: str) -> tuple[Entry, ...]:
        """Every table the Committee publishes, with its name, description and topic."""
        self._check_lang(lang)
        hit = self._catalogues.get(lang)
        if hit is not None and hit[0] > self._now():
            return hit[1]
        body = await self._get_json("tables", {"lang": lang}, MAX_CATALOGUE_BYTES)
        entries = parse_catalogue(body, lang)
        self._catalogues[lang] = (self._now() + CATALOGUE_TTL, entries)
        return entries

    async def table(self, table_id: str, lang: str) -> Table:
        """One table's rows. The API has no filters, so the whole table is read and cached."""
        self._check_lang(lang)
        if not TABLE_ID.fullmatch(table_id):
            raise NotFound(f"{table_id!r} is not a table id such as DT_AA_001.")
        key = (table_id, lang)
        hit = self._tables.get(key)
        if hit is not None and hit[0] > self._now():
            self._tables.move_to_end(key)
            return hit[1]
        params = {"table_id": table_id, "lang": lang}
        table = parse_table(
            await self._get_json("data", params, self._max_bytes, table_id=table_id)
        )
        self._tables[key] = (self._now() + TABLE_TTL, table)
        self._tables.move_to_end(key)
        while len(self._tables) > TABLE_CACHE_SIZE:
            self._tables.popitem(last=False)
        return table

    @staticmethod
    def _check_lang(lang: str) -> None:
        if lang not in LANGS:
            raise AzstatError(f"lang must be one of {', '.join(LANGS)}.")

    async def _get_json(
        self, path: str, params: dict[str, str], cap: int, *, table_id: str | None = None
    ) -> dict[str, Any]:
        status, raw = await self._fetch(path, params, cap)
        try:
            body = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            raise AzstatError(f"The API's answer to {path} is not JSON.") from exc
        if not isinstance(body, dict):
            raise UnexpectedShape(f"The API's answer to {path} is not a JSON object.")
        if status != 200 or not body.get("success"):
            message = body.get("message") or f"HTTP {status}"
            if status == 400 and table_id and "tapılmadı" in str(message):
                raise NotFound(f"The Committee has no table {table_id!r}.")
            raise AzstatError(f"The API rejected {path}: {message}")
        return body

    async def _fetch(self, path: str, params: dict[str, str], cap: int) -> tuple[int, bytes]:
        url = f"{self._api_base}/{path}"
        host = urlsplit(url).hostname or ""
        error: Exception
        for attempt in (1, 2):
            await self._throttle(host)
            try:
                async with self._client().stream("GET", url, params=params) as response:
                    status = response.status_code
                    if status in BLOCKED_CODES:
                        raise EndpointBlocked(
                            f"The Committee's API refuses {path} (HTTP {status}). "
                            "This server does not retry or work around it."
                        )
                    if 300 <= status < 400:
                        raise AzstatError(f"The API redirected {path}; redirects are not followed.")
                    if status < 500:
                        return status, await self._read(response, cap)
                    error = AzstatError(f"HTTP {status}")
            except NETWORK_ERRORS as exc:
                error = exc
            if attempt == 2:
                raise AzstatError(f"The API did not answer {path}: {error}") from error
            await self._sleep(self._retry_delay)
        raise AssertionError("unreachable")  # pragma: no cover

    async def _read(self, response: httpx.Response, cap: int) -> bytes:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cap:
            raise TableTooLarge(self._too_large(cap, int(declared)))
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > cap:
                raise TableTooLarge(self._too_large(cap))
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _too_large(cap: int, size: int | None = None) -> str:
        megabytes = cap / (1024 * 1024)
        limit = f"{megabytes:g} MB" if megabytes >= 1 else f"{cap:,} bytes"
        if size is None:
            return f"The answer is larger than the {limit} this server reads."
        return f"The answer is {size:,} bytes; this server reads at most {limit}."
