"""HTTP access to the opendata.az CKAN API and to the resource files it lists."""

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from . import __version__

DEFAULT_API_BASE = "https://admin.opendata.az/api/3/action"
DEFAULT_RESOURCE_HOSTS = ("opendata.az", "azstat.gov.az")
MAX_RESOURCE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 4
SEARCH_TTL = 600.0
FACETS_TTL = 3600.0
CACHE_SIZE = 256
RETRY_DELAY = 0.5
REDIRECT_CODES = {301, 302, 303, 307, 308}
BLOCKED_CODES = {403, 429}
NETWORK_ERRORS = (httpx.RequestError, httpx.InvalidURL)
FACET_FIELDS = '["organization","groups","license_id","res_format"]'


class PortalError(Exception):
    """The portal or a resource host could not be reached or answered something unexpected."""


class NotFound(PortalError):
    """The portal has no such dataset or file."""


class EndpointBlocked(PortalError):
    """The portal refuses an endpoint this server relies on, or asks it to slow down (403, 429)."""


class ResourceRefused(PortalError):
    """A resource is not fetched: its host is not allowed, or the file is too large."""

    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class OpenDataClient:
    """Async client for the portal's CKAN API with a cache and a one-request-per-second limit."""

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        *,
        api_base: str = DEFAULT_API_BASE,
        resource_hosts: tuple[str, ...] = DEFAULT_RESOURCE_HOSTS,
        max_bytes: int = MAX_RESOURCE_BYTES,
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
        self._hosts = tuple(host.strip().lower() for host in resource_hosts if host.strip())
        self._max_bytes = max_bytes
        self._min_interval = min_interval
        self._retry_delay = retry_delay
        self._now = now
        self._sleep = sleep
        self._cache: dict[Any, tuple[float, Any]] = {}
        self._last_request: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def from_env(cls) -> "OpenDataClient":
        """Read OPENDATA_AZ_API_BASE and OPENDATA_AZ_RESOURCE_HOSTS (comma separated), if set."""
        hosts = os.environ.get("OPENDATA_AZ_RESOURCE_HOSTS")
        return cls(
            api_base=os.environ.get("OPENDATA_AZ_API_BASE", DEFAULT_API_BASE),
            resource_hosts=tuple(hosts.split(",")) if hosts else DEFAULT_RESOURCE_HOSTS,
        )

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(20.0),
                follow_redirects=False,
                headers={"User-Agent": f"azerbaijan-mcp-opendata/{__version__}"},
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

    def _recall(self, key: Any) -> Any:
        hit = self._cache.get(key)
        return hit[1] if hit is not None and hit[0] > self._now() else None

    def _remember(self, key: Any, ttl: float, value: Any) -> Any:
        if len(self._cache) >= CACHE_SIZE:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (self._now() + ttl, value)
        return value

    def host_allowed(self, url: str) -> bool:
        """True for https URLs on an allowed host or one of its subdomains, default port only."""
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return False
        host = (parts.hostname or "").lower()
        return (
            parts.scheme == "https"
            and port in (None, 443)
            and any(host == allowed or host.endswith("." + allowed) for allowed in self._hosts)
        )

    async def _api(self, action: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self._api_base}/{action}"
        host = urlsplit(url).hostname or ""
        for attempt in (1, 2):
            await self._throttle(host)
            try:
                response = await self._client().get(url, params=params)
            except NETWORK_ERRORS as exc:
                error: Exception = exc
            else:
                if response.status_code == 404:
                    raise NotFound("The portal has no such dataset.")
                if response.status_code in BLOCKED_CODES:
                    raise EndpointBlocked(
                        f"The portal refuses {action} (HTTP {response.status_code}). "
                        "This server does not retry or work around it."
                    )
                if response.status_code < 500:
                    return self._unwrap(action, response)
                error = PortalError(f"HTTP {response.status_code}")
            if attempt == 2:
                raise PortalError(f"The portal did not answer {action}: {error}") from error
            await self._sleep(self._retry_delay)
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _unwrap(action: str, response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise PortalError(f"The portal's answer to {action} is not JSON.") from exc
        if response.status_code != 200 or not body.get("success"):
            message = (body.get("error") or {}).get("message") or f"HTTP {response.status_code}"
            raise PortalError(f"The portal rejected {action}: {message}")
        return body["result"]

    async def search(
        self, *, q: str | None, fq: list[str], rows: int, start: int, sort: str
    ) -> dict[str, Any]:
        params = {"rows": str(rows), "start": str(start), "sort": sort}
        if q:
            params["q"] = q
        if fq:
            params["fq"] = " ".join(fq)
        key = ("search", tuple(sorted(params.items())))
        cached = self._recall(key)
        if cached is not None:
            return cached
        return self._remember(key, SEARCH_TTL, await self._api("package_search", params))

    async def show(self, dataset_id: str) -> dict[str, Any]:
        key = ("show", dataset_id)
        cached = self._recall(key)
        if cached is not None:
            return cached
        try:
            result = await self._api("package_show", {"id": dataset_id})
        except NotFound as exc:
            raise NotFound(f"The portal has no dataset {dataset_id!r}.") from exc
        return self._remember(key, SEARCH_TTL, result)

    async def facets(self) -> dict[str, Any]:
        """Organization, group, licence and format counts for the whole portal, in one request."""
        key = ("facets",)
        cached = self._recall(key)
        if cached is not None:
            return cached
        params = {"rows": "0", "facet.field": FACET_FIELDS, "facet.limit": "-1"}
        return self._remember(key, FACETS_TTL, await self._api("package_search", params))

    async def fetch_resource(self, url: str) -> tuple[bytes, str]:
        """Download a resource file: allowed hosts only, redirects checked, size capped."""
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if not self.host_allowed(current):
                raise self._not_allowed(redirected=current != url)
            await self._throttle(urlsplit(current).hostname or "")
            try:
                async with self._client().stream("GET", current) as response:
                    if response.status_code in REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            raise PortalError("The file's host sent a redirect without a target.")
                        current = urljoin(current, location)
                        continue
                    if response.status_code == 404:
                        raise NotFound("The file is gone (HTTP 404).")
                    if response.status_code >= 400:
                        raise PortalError(f"The file's host answered HTTP {response.status_code}.")
                    return await self._read(response)
            except NETWORK_ERRORS as exc:
                raise PortalError(f"The file could not be fetched: {type(exc).__name__}.") from exc
        raise PortalError("The file redirects too many times.")

    async def _read(self, response: httpx.Response) -> tuple[bytes, str]:
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > self._max_bytes:
            raise ResourceRefused("too_large", self._too_large(int(declared)))
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self._max_bytes:
                raise ResourceRefused("too_large", self._too_large())
            chunks.append(chunk)
        return b"".join(chunks), response.headers.get("content-type", "")

    def _not_allowed(self, *, redirected: bool) -> ResourceRefused:
        where = "redirects away from" if redirected else "is not on"
        hosts = ", ".join(self._hosts)
        return ResourceRefused("link_only", f"The file {where} an allowed https host ({hosts}).")

    def _too_large(self, size: int | None = None) -> str:
        megabytes = self._max_bytes / (1024 * 1024)
        limit = f"{megabytes:g} MB" if megabytes >= 1 else f"{self._max_bytes:,} bytes"
        if size is None:
            return f"The file is larger than the {limit} preview limit."
        return f"The file is {size:,} bytes; the preview limit is {limit}."
