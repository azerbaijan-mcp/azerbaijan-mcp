"""The serving index: a small SQLite file derived from the source database.

The source is the extraction the user supplies. It is opened read-only and never written. What the
server needs beyond it is derived once and cached, one file for each source, kept while the source's
size and modification time stay the same:

* `entry`: the text with its lines joined, the page, the etymology note;
* `form`: every spelling of every headword (`AB(B)ASI` has two), also without accents;
* `fts`: a full-text index over text folded the Azerbaijani way. The source's own index is not:
  it misses every word that starts a sentence with a capital İ.
"""

import hashlib
import os
import sqlite3
import sys
import time
from contextlib import closing, suppress
from pathlib import Path

from . import text as rules
from .errors import BadDatabase

INDEX_VERSION = 2
STALE_TEMP_SECONDS = 600  # a build takes seconds: a temporary file idle for ten minutes is dead
DEFAULT_TITLE = "Azərbaycan dilinin izahlı lüğəti"
SOURCE_COLUMNS = frozenset(
    {
        "id",
        "volume",
        "headword",
        "homonym_index",
        "entry_text",
        "start_page",
        "end_page",
        "start_column",
    }
)
SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entry(
    id INTEGER PRIMARY KEY,
    volume INTEGER NOT NULL,
    page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    col INTEGER NOT NULL,
    headword TEXT NOT NULL,
    homonym INTEGER,
    origin TEXT,
    text TEXT NOT NULL
);
CREATE TABLE form(form TEXT NOT NULL, plain TEXT NOT NULL, entry_id INTEGER NOT NULL);
CREATE VIRTUAL TABLE fts USING fts5(
    head, body, content='', tokenize='unicode61 remove_diacritics 0'
);
"""
INDEXES = "CREATE INDEX form_form ON form(form); CREATE INDEX form_plain ON form(plain);"


def default_cache_dir() -> Path:
    """Where the index lives: IZAHLI_CACHE_DIR, or the user's cache folder."""
    if override := os.environ.get("IZAHLI_CACHE_DIR", "").strip():
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "azerbaijan-mcp" / "izahli"


def _uri(path: Path) -> str:
    """The URI that opens a file read-only.

    Path.as_uri() writes a network path as file://host/share/..., which SQLite refuses: it wants
    the host after four slashes. abspath, not resolve, so that a mapped drive stays a drive letter.
    """
    uri = Path(os.path.abspath(path)).as_uri()
    if not uri.startswith("file:///"):
        uri = "file:////" + uri.removeprefix("file://")
    return uri + "?mode=ro"


def connect(path: Path) -> sqlite3.Connection:
    """Open a SQLite file read-only."""
    return sqlite3.connect(_uri(path), uri=True)


def index_path(source: Path, cache: Path) -> Path:
    """Where the index of a source lives: a file for each source, so that two databases can share
    a cache folder without serving each other's text."""
    digest = hashlib.sha256(os.path.abspath(source).encode("utf-8", "surrogatepass")).hexdigest()
    return cache / f"index-{digest[:12]}.sqlite"


def source_stamp(source: Path) -> str:
    stat = source.stat()
    return f"{INDEX_VERSION}:{stat.st_size}:{stat.st_mtime_ns}"


def ensure(source: Path, cache: Path) -> Path:
    """The path of an index that matches the source, built now if there is none."""
    if not source.is_file():
        raise BadDatabase(f"The dictionary database {source} does not exist or is not a file.")
    stamp = source_stamp(source)
    index = index_path(source, cache)
    if _current(index, stamp):
        return index
    try:
        cache.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BadDatabase(
            f"Cannot create the index folder {cache}: {exc}. Set IZAHLI_CACHE_DIR to a folder "
            "that can be written."
        ) from exc
    remove_stale_temp(cache)
    temp = cache / f"{index.name}.{os.getpid()}.tmp"
    try:
        _build(source, temp, stamp)
        try:
            os.replace(temp, index)
        except PermissionError as exc:
            # Windows will not replace a file another process has open. If that process built the
            # same index meanwhile, use it.
            if not _current(index, stamp):
                raise BadDatabase(
                    f"The index {index} is in use by another process and out of date. Close the "
                    "other copy of the server and try again."
                ) from exc
    except OSError as exc:
        raise BadDatabase(f"Cannot write the index in {cache}: {exc}") from exc
    finally:
        temp.unlink(missing_ok=True)
    return index


def remove_stale_temp(cache: Path) -> None:
    """Delete the half-written files that builds and downloads which were killed left behind."""
    cutoff = time.time() - STALE_TEMP_SECONDS
    for leftover in cache.glob("*.tmp"):
        with suppress(OSError):
            if leftover.stat().st_mtime < cutoff:
                leftover.unlink()


def title(index: Path) -> str:
    with closing(connect(index)) as db:
        row = db.execute("SELECT value FROM meta WHERE key = 'title'").fetchone()
    return row[0] if row else DEFAULT_TITLE


def _current(index: Path, stamp: str) -> bool:
    if not index.is_file():
        return False
    try:
        with closing(connect(index)) as db:
            row = db.execute("SELECT value FROM meta WHERE key = 'stamp'").fetchone()
    except sqlite3.Error:
        return False
    return row is not None and row[0] == stamp


def read_source(source: Path) -> tuple[dict[str, str], list[tuple]]:
    """The source's metadata and entries, after checking it has what the index needs."""
    try:
        with closing(connect(source)) as db:
            columns = {row[1] for row in db.execute("PRAGMA table_info(entries)")}
            if not columns:
                raise BadDatabase(f"{source} has no `entries` table, so it is not a dictionary.")
            if missing := SOURCE_COLUMNS - columns:
                raise BadDatabase(
                    f"The `entries` table of {source} lacks the column(s) "
                    f"{', '.join(sorted(missing))}."
                )
            try:
                pairs = db.execute("SELECT key, value FROM metadata").fetchall()
            except sqlite3.OperationalError:
                pairs = []
            metadata = {str(key): str(value) for key, value in pairs}
            rows = db.execute(
                "SELECT id, volume, headword, homonym_index, entry_text, start_page, end_page, "
                "start_column FROM entries ORDER BY id"
            ).fetchall()
    except sqlite3.Error as exc:
        raise BadDatabase(f"{source} cannot be read as a SQLite database: {exc}") from exc
    if not rows:
        raise BadDatabase(f"The `entries` table of {source} is empty.")
    declared = metadata.get("entry_count", "")
    if declared.isdigit() and int(declared) != len(rows):
        raise BadDatabase(
            f"{source} holds {len(rows):,} entries but its metadata says {int(declared):,}: the "
            "file looks incomplete."
        )
    return metadata, rows


def _build(source: Path, target: Path, stamp: str) -> None:
    metadata, rows = read_source(source)
    spelled = [rules.headword_forms(row[2]) for row in rows]
    vocabulary = rules.build_vocabulary(
        (row[4] for row in rows), (form for spellings in spelled for form in spellings)
    )
    entries, forms, search = [], [], []
    for row, spellings in zip(rows, spelled, strict=True):
        id_, volume, headword, homonym, raw, page, end_page, column = row
        text = rules.dewrap(raw, vocabulary)
        entries.append(
            (
                id_,
                volume,
                page,
                end_page,
                column,
                rules.display_headword(headword, homonym),
                homonym,
                rules.origin_of(text),
                text,
            )
        )
        forms.extend((spelling, rules.accent_free(spelling), id_) for spelling in spellings)
        search.append((id_, " ".join(spellings), rules.fold(text)))
    meta = [
        ("stamp", stamp),
        ("title", metadata.get("database_title") or DEFAULT_TITLE),
        ("entries", str(len(entries))),
    ]
    target.unlink(missing_ok=True)
    db = sqlite3.connect(target)
    try:
        db.executescript("PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;")
        try:
            db.executescript(SCHEMA)
        except sqlite3.OperationalError as exc:
            raise BadDatabase(f"This Python's SQLite cannot build the index: {exc}") from exc
        with db:
            db.executemany("INSERT INTO entry VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", entries)
            db.executemany("INSERT INTO form VALUES (?, ?, ?)", forms)
            db.executemany("INSERT INTO fts(rowid, head, body) VALUES (?, ?, ?)", search)
            db.executemany("INSERT INTO meta VALUES (?, ?)", meta)
        db.executescript(INDEXES)
        db.execute("INSERT INTO fts(fts) VALUES ('optimize')")
        db.commit()
    finally:
        db.close()
