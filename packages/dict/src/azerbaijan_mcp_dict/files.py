"""Giving a finished file its final name, and telling a whole SQLite file from a cut-short one."""

import errno
import os
import shutil
from contextlib import suppress
from pathlib import Path

CHUNK = 1 << 20
SQLITE_MAGIC = b"SQLite format 3\x00"
SQLITE_HEADER = 100


def move_into_place(source: Path, target: Path) -> None:
    """Rename `source` to `target`, replacing what is there; where renames are refused, copy it.

    A folder that Windows redirects for a packaged app, such as the cache of a server the Claude
    desktop app starts, refuses every rename in it with WinError 17, which Python reports as EXDEV,
    although creating and copying files there works. A copy is not atomic, so one that fails is
    removed rather than left under the final name. `source` is left for its owner to delete. Any
    other error, a PermissionError for a file in use among them, is raised as it is.
    """
    try:
        os.replace(source, target)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
    with source.open("rb") as finished:
        out = target.open("wb")  # a file in use fails here, before anything of it is touched
        try:
            with out:
                shutil.copyfileobj(finished, out, CHUNK)
        except BaseException:
            with suppress(OSError):
                target.unlink()
            raise


def is_whole_sqlite(path: Path) -> bool:
    """Whether `path` is a SQLite file with all its pages, which a killed copy leaves it without.

    The header gives the size of a page and how many pages the file has. The count is trusted only
    when the header says it is current: the change counter and the version-valid-for number agree
    (https://www.sqlite.org/fileformat2.html#in_header_database_size). Otherwise the file counts as
    whole when its first page is there.
    """
    try:
        with path.open("rb") as file:
            header = file.read(SQLITE_HEADER)
            size = os.fstat(file.fileno()).st_size
    except OSError:
        return False
    if len(header) < SQLITE_HEADER or not header.startswith(SQLITE_MAGIC):
        return False
    page = int.from_bytes(header[16:18], "big")
    page = 65536 if page == 1 else page
    if not 512 <= page <= 65536 or page & (page - 1):
        return False
    pages = int.from_bytes(header[28:32], "big")
    current = pages > 0 and header[24:28] == header[92:96]
    return size >= (pages if current else 1) * page
