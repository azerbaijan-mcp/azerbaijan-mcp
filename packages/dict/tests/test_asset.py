import gzip
import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from azerbaijan_mcp_dict import asset
from azerbaijan_mcp_dict.errors import BadDatabase
from azerbaijan_mcp_dict.store import Store

COLUMNS = [
    "id",
    "volume",
    "headword",
    "homonym_index",
    "entry_text",
    "start_page",
    "end_page",
    "start_column",
]


def unpack(packed: asset.Packed, folder: Path) -> Path:
    plain = folder / "unpacked.sqlite"
    plain.write_bytes(gzip.decompress(packed.path.read_bytes()))
    return plain


def test_the_asset_holds_only_what_the_server_reads(asset_pack, entries, tmp_path):
    plain = unpack(asset_pack, tmp_path)
    with closing(sqlite3.connect(plain)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert tables == {"entries", "metadata"}
        assert [row[1] for row in db.execute("PRAGMA table_info(entries)")] == COLUMNS
        assert db.execute("SELECT count(*) FROM entries").fetchone()[0] == len(entries)
        text = " ".join(row[0] for row in db.execute("SELECT headword || entry_text FROM entries"))
    assert "DECOY" not in text  # the columns the server never reads are not packed
    assert "MUST NOT" not in text


def test_the_asset_says_what_it_is(asset_pack, entries):
    data = asset_pack.path.read_bytes()
    assert asset_pack.entries == len(entries)
    assert asset_pack.size == len(data)
    assert asset_pack.sha256 == hashlib.sha256(data).hexdigest()


def test_the_same_database_packs_to_the_same_bytes(source_db, asset_pack, tmp_path):
    again = asset.pack(source_db, tmp_path / "again.sqlite.gz")
    assert again.sha256 == asset_pack.sha256


def test_the_metadata_is_kept_except_what_describes_a_table_the_asset_lacks(
    tmp_path, make_source, entries
):
    source = make_source(
        tmp_path / "source.sqlite",
        metadata={
            "database_title": "A title",
            "entry_count": str(len(entries)),
            "volume_1_source_sha256": "abc",
            "fts_query_hint": "SELECT * FROM entries_fts",
        },
    )
    plain = unpack(asset.pack(source, tmp_path / "out.sqlite.gz"), tmp_path)
    with closing(sqlite3.connect(plain)) as db:
        kept = dict(db.execute("SELECT key, value FROM metadata"))
    assert kept == {
        "database_title": "A title",
        "entry_count": str(len(entries)),
        "volume_1_source_sha256": "abc",
    }


def test_an_unpacked_asset_is_a_source_the_store_reads(asset_pack, tmp_path):
    store = Store(unpack(asset_pack, tmp_path), tmp_path / "cache")
    out = store.define("kitab", 500)
    assert [entry.headword for entry in out.entries] == ["KİTAB"]
    assert out.source == "Invented test dictionary"


def test_a_database_the_server_cannot_read_is_not_packed(tmp_path):
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"this is not a database" * 50)
    target = tmp_path / "out.sqlite.gz"
    with pytest.raises(BadDatabase):
        asset.pack(junk, target)
    assert not target.exists()


def test_main_prints_what_to_pin(source_db, entries, tmp_path, capsys):
    target = tmp_path / "out.sqlite.gz"
    assert asset.main([str(source_db), str(target)]) == 0
    printed = dict(line.split() for line in capsys.readouterr().out.splitlines())
    assert printed["entries"] == str(len(entries))
    assert printed["size"] == str(target.stat().st_size)
    assert printed["sha256"] == hashlib.sha256(target.read_bytes()).hexdigest()


def test_main_without_the_two_paths_says_how_to_use_it(capsys):
    assert asset.main([]) == 2
    assert "python -m azerbaijan_mcp_dict.asset" in capsys.readouterr().err
