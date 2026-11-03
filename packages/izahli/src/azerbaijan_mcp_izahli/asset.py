"""The database as the project publishes it: the columns the server reads and the metadata,
gzip-compressed. Anything the server can read as a source can be packed:

    python -m azerbaijan_mcp_izahli.asset source.sqlite izahli-dictionary-1.sqlite.gz

prints the entry count, the size and the SHA-256 that `database.py` pins.
"""

import gzip
import hashlib
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from . import index

SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    volume INTEGER NOT NULL,
    headword TEXT NOT NULL,
    homonym_index INTEGER,
    entry_text TEXT NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    start_column INTEGER NOT NULL
);
"""
# Describes tables the asset does not have.
DROPPED_METADATA = frozenset({"fts_query_hint"})


@dataclass(frozen=True)
class Packed:
    path: Path
    entries: int
    size: int
    sha256: str


def pack(source: Path, target: Path) -> Packed:
    """Write the asset for a source database, which is read, checked and never changed."""
    metadata, rows = index.read_source(source)
    with tempfile.TemporaryDirectory() as folder:
        plain = Path(folder) / "dictionary.sqlite"
        with closing(sqlite3.connect(plain)) as db:
            db.executescript(SCHEMA)
            with db:
                db.executemany("INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
                db.executemany(
                    "INSERT INTO metadata VALUES (?, ?)",
                    sorted((k, v) for k, v in metadata.items() if k not in DROPPED_METADATA),
                )
            db.execute("VACUUM")
        # mtime=0 and no file name inside: the same database packs to the same bytes
        with (
            plain.open("rb") as raw,
            target.open("wb") as out,
            gzip.GzipFile(filename="", mode="wb", fileobj=out, compresslevel=9, mtime=0) as zipped,
        ):
            shutil.copyfileobj(raw, zipped)
    packed = target.read_bytes()
    return Packed(target, len(rows), len(packed), hashlib.sha256(packed).hexdigest())


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    packed = pack(Path(argv[0]), Path(argv[1]))
    print(f"entries {packed.entries}")
    print(f"size {packed.size}")
    print(f"sha256 {packed.sha256}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
