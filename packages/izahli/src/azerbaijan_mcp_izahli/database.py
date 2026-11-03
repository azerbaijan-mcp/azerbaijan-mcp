"""The dictionary database the project publishes, downloaded once and kept in the cache folder.

The file is a release asset of this project's repository (asset.py packs it). Its SHA-256 is pinned
here, so whatever the address serves is checked before any of it is used. The download keeps to the
manners the data policy asks for: an honest User-Agent that names this project, one request, one
retry for a network error or a server error, a full stop on HTTP 403 and 429, and a ceiling on size.
"""

import gzip
import hashlib
import logging
import os
import time
import zlib
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import __version__, index
from .errors import DownloadFailed

log = logging.getLogger(__name__)

PROJECT_URL = "https://github.com/azerbaijan-mcp/azerbaijan-mcp"
DATA_URL = f"{PROJECT_URL}/releases/download/izahli-data-1/izahli-dictionary-1.sqlite.gz"
DATA_SHA256 = "44515ffca32d7cefc9f659bbe1ecefa82dc6908f17b5d434daffd1f921162022"
DATA_SIZE = 5_657_352  # bytes of the gzip file at DATA_URL, which DATA_SHA256 is the hash of
MEGABYTE = 1024 * 1024
MAX_DOWNLOAD_BYTES = 100 * MEGABYTE
MAX_DATABASE_BYTES = 500 * MEGABYTE  # what the gzip file may expand to
RETRY_DELAY = 1.0
BLOCKED = {403, 429}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
HINT = "Download it by hand and point IZAHLI_DB at the file, or try again later."


def ensure(
    cache: Path,
    *,
    url: str | None = None,
    sha256: str | None = None,
    transport: httpx.BaseTransport | None = None,
    max_bytes: int | None = None,
    max_database_bytes: int | None = None,
    retry_delay: float | None = None,
) -> Path:
    """The published database in the cache folder, downloaded now if it is not there.

    The defaults are the pinned address, checksum and limits; tests and mirrors give their own.
    """
    sha256 = sha256 or DATA_SHA256
    target = cache / f"dictionary-{sha256[:12]}.sqlite"
    if target.is_file():
        return target
    url = url or DATA_URL
    _check_url(url)
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DownloadFailed(
            f"Cannot create the folder {cache} for the dictionary database: {exc}. Set "
            "IZAHLI_CACHE_DIR to a folder that can be written."
        ) from exc
    index.remove_stale_temp(cache)
    packed = cache / f"{target.name}.{os.getpid()}.gz.tmp"
    plain = cache / f"{target.name}.{os.getpid()}.tmp"
    try:
        log.info("Downloading the dictionary database (%.1f MB) from %s", DATA_SIZE / 1e6, url)
        with _client(transport) as client:
            got = _download(
                client,
                url,
                packed,
                max_bytes or MAX_DOWNLOAD_BYTES,
                RETRY_DELAY if retry_delay is None else retry_delay,
            )
        if got != sha256:
            raise DownloadFailed(
                f"The file downloaded from {url} does not match the published checksum (its "
                f"SHA-256 starts {got[:12]}, expected {sha256[:12]}), so it was not used. {HINT}"
            )
        _unpack(packed, plain, max_database_bytes or MAX_DATABASE_BYTES)
        try:
            os.replace(plain, target)
        except PermissionError:
            if not target.is_file():  # Windows will not replace a file another process has open
                raise
    except OSError as exc:
        raise DownloadFailed(f"Cannot write the dictionary database in {cache}: {exc}") from exc
    finally:
        packed.unlink(missing_ok=True)
        plain.unlink(missing_ok=True)
    return target


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme == "https" or (parts.scheme == "http" and parts.hostname in LOOPBACK):
        return
    raise DownloadFailed(
        f"The database address {url!r} must start with https:// (http:// only for this computer)."
    )


def _client(transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(
        transport=transport,
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
        max_redirects=5,
        headers={"User-Agent": f"azerbaijan-mcp-izahli/{__version__} (+{PROJECT_URL})"},
    )


def _download(
    client: httpx.Client, url: str, destination: Path, max_bytes: int, retry_delay: float
) -> str:
    """Stream the answer into `destination` and return its SHA-256.

    A network error or a 5xx is tried once more; anything else stops here.
    """
    problem = ""
    for attempt in range(2):
        if attempt:
            time.sleep(retry_delay)
        try:
            with client.stream("GET", url) as response:
                status = response.status_code
                if status in BLOCKED:
                    raise DownloadFailed(
                        f"{urlsplit(url).netloc} refuses the download (HTTP {status}). {HINT}"
                    )
                if status == 404:
                    raise DownloadFailed(
                        f"The dictionary database is not published at {url} (HTTP 404). {HINT}"
                    )
                if status >= 500:
                    problem = f"HTTP {status}"
                    continue
                if status != 200:
                    raise DownloadFailed(f"{url} answered HTTP {status}. {HINT}")
                return _save(response, destination, max_bytes)
        except httpx.RequestError as exc:
            problem = f"{type(exc).__name__}: {exc}"
    raise DownloadFailed(
        f"The dictionary database could not be downloaded from {url} ({problem}). {HINT}"
    )


def _save(response: httpx.Response, destination: Path, max_bytes: int) -> str:
    try:
        declared = int(response.headers.get("content-length", "0"))
    except ValueError:
        declared = 0
    if declared > max_bytes:
        raise DownloadFailed(_too_large(max_bytes))
    digest, size = hashlib.sha256(), 0
    with destination.open("wb") as out:
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > max_bytes:
                raise DownloadFailed(_too_large(max_bytes))
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest()


def _size(limit: int) -> str:
    return f"{limit // MEGABYTE} MB" if limit >= MEGABYTE else f"{limit:,} bytes"


def _too_large(limit: int) -> str:
    return f"The dictionary database is larger than {_size(limit)}; not downloaded."


def _unpack(source: Path, target: Path, limit: int) -> None:
    written = 0
    try:
        with gzip.open(source, "rb") as zipped, target.open("wb") as out:
            while chunk := zipped.read(1 << 20):
                written += len(chunk)
                if written > limit:
                    raise DownloadFailed(
                        f"The dictionary database expands to more than {_size(limit)}; not used."
                    )
                out.write(chunk)
    except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
        raise DownloadFailed(
            f"The downloaded file is not a valid gzip file ({exc}). {HINT}"
        ) from exc
