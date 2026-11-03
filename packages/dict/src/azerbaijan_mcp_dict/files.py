"""Giving a finished file its final name."""

import errno
import os
import shutil
from contextlib import suppress
from pathlib import Path

CHUNK = 1 << 20


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
