import hashlib
import os
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import pytest

from azerbaijan_mcp_dict import index
from azerbaijan_mcp_dict.errors import BadDatabase


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path, sql: str, *args):
    with closing(index.connect(path)) as db:
        return db.execute(sql, args).fetchall()


def touch_later(path: Path) -> None:
    """Change the source's modification time, as a replaced file would."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


@pytest.fixture
def source(tmp_path, make_source) -> Path:
    return make_source(tmp_path / "source.sqlite")


def test_the_index_holds_the_entries_their_spellings_and_a_title(source, tmp_path, entries, title):
    path = index.ensure(source, tmp_path / "cache")
    assert path == index.index_path(source, tmp_path / "cache")
    assert rows(path, "SELECT count(*) FROM entry")[0][0] == len(entries)
    assert index.title(path) == title
    assert rows(path, "SELECT value FROM meta WHERE key = 'entries'") == [(str(len(entries)),)]
    # ACGÖZ(LÜ) is two spellings, and AXÇA has the one
    spelled = {form for (form,) in rows(path, "SELECT form FROM form WHERE entry_id IN (1, 5)")}
    assert spelled == {"acgöz", "acgözlü", "axça"}
    assert rows(path, "SELECT plain FROM form WHERE form = 'şəhər'") == [("seher",)]


def test_the_index_has_the_text_joined_and_never_reads_the_decoy_columns(source, tmp_path):
    path = index.ensure(source, tmp_path / "cache")
    ((text, headword, origin),) = rows(
        path, "SELECT text, headword, origin FROM entry WHERE headword = 'KİTAB'"
    )
    assert text.startswith("is. [ər.] Yazılı")
    assert origin == "ər."
    assert "DECOY" not in text + headword
    assert "MUST NOT" not in text + headword
    assert rows(path, "SELECT count(*) FROM entry WHERE text LIKE '%' || char(10) || '%'") == [(0,)]


def test_the_source_is_never_written(source, tmp_path):
    before, stat = digest(source), source.stat()
    index.ensure(source, tmp_path / "cache")
    after = source.stat()
    assert digest(source) == before
    assert (after.st_size, after.st_mtime_ns) == (stat.st_size, stat.st_mtime_ns)
    # no journal or other file next to it: the folder holds the source and the cache, nothing else
    assert sorted(path.name for path in source.parent.iterdir()) == ["cache", "source.sqlite"]


def test_a_current_index_is_reused_and_a_changed_source_is_indexed_again(
    source, tmp_path, count_builds
):
    cache = tmp_path / "cache"
    index.ensure(source, cache)
    index.ensure(source, cache)
    assert len(count_builds) == 1
    touch_later(source)
    index.ensure(source, cache)
    assert len(count_builds) == 2
    index.ensure(source, cache)
    assert len(count_builds) == 2


def test_an_index_that_cannot_be_read_is_replaced(source, tmp_path, entries, count_builds):
    cache = tmp_path / "cache"
    cache.mkdir()
    target = index.index_path(source, cache)
    target.write_bytes(b"this is not a database")
    path = index.ensure(source, cache)
    assert (path, len(count_builds)) == (target, 1)
    assert rows(path, "SELECT count(*) FROM entry")[0][0] == len(entries)
    assert [p.name for p in cache.iterdir()] == [target.name]  # no temporary file left


def test_two_databases_get_an_index_each_in_one_cache_folder(tmp_path, make_source):
    cache = tmp_path / "cache"
    one = make_source(tmp_path / "one.sqlite", [("SU", None, "is. one.", 1, 26, 1)])
    two = make_source(tmp_path / "two.sqlite", [("SU", None, "is. two.", 1, 26, 1)])
    first, second = index.ensure(one, cache), index.ensure(two, cache)
    assert first != second
    assert rows(first, "SELECT text FROM entry") == [("is. one.",)]
    assert rows(second, "SELECT text FROM entry") == [("is. two.",)]
    assert index.ensure(one, cache) == first


def test_the_leftovers_of_a_killed_build_are_removed_but_a_build_under_way_is_not(source, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    old, young = cache / "index-1.sqlite.111.tmp", cache / "index-2.sqlite.222.tmp"
    for leftover in (old, young):
        leftover.write_bytes(b"half a database")
    stat = old.stat()
    long_ago = stat.st_mtime_ns - 2 * index.STALE_TEMP_SECONDS * 1_000_000_000
    os.utime(old, ns=(long_ago, long_ago))
    index.ensure(source, cache)
    assert not old.exists()
    assert young.exists()


@pytest.mark.parametrize(
    ("uri", "read_only"),
    [
        ("file:///C:/Users/me/x.sqlite", "file:///C:/Users/me/x.sqlite?mode=ro"),
        ("file:///home/me/x.sqlite", "file:///home/me/x.sqlite?mode=ro"),
        # a network path: SQLite wants the host after four slashes
        ("file://server/share/x.sqlite", "file:////server/share/x.sqlite?mode=ro"),
    ],
)
def test_the_read_only_uri_of_a_local_and_of_a_network_path(monkeypatch, uri, read_only):
    monkeypatch.setattr(index.Path, "as_uri", lambda self: uri)
    assert index._uri(Path("whatever")) == read_only


@pytest.mark.skipif(sys.platform != "win32", reason="network paths are a Windows matter")
def test_a_database_and_a_cache_on_a_network_path_work(source, tmp_path, monkeypatch):
    drive, rest = os.path.splitdrive(source)
    host = os.environ.get("COMPUTERNAME")
    unc = Path(f"\\\\{host}\\{drive[0]}$" + rest)  # the administrative share of this computer
    if not host or not unc.exists():
        pytest.skip("the computer's administrative share is not reachable")
    path = index.ensure(unc, Path(f"\\\\{host}\\{drive[0]}$" + os.path.splitdrive(tmp_path)[1]))
    assert rows(path, "SELECT count(*) FROM entry")[0][0] > 0


def test_a_build_that_fails_leaves_no_temporary_file(tmp_path, make_source):
    source = make_source(tmp_path / "source.sqlite", metadata={"entry_count": "99"})
    cache = tmp_path / "cache"
    with pytest.raises(BadDatabase):
        index.ensure(source, cache)
    assert list(cache.iterdir()) == []


def test_when_another_process_built_the_same_index_first_it_is_used(source, tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    real = index._build

    def build_and_race(source, target, stamp):
        real(source, target, stamp)
        shutil.copy(target, index.index_path(source, cache))  # the other process finishes first

    def refuse(*_):
        raise PermissionError("the file is in use")  # Windows will not replace an open file

    monkeypatch.setattr(index, "_build", build_and_race)
    monkeypatch.setattr(index.os, "replace", refuse)
    assert index.ensure(source, cache) == index.index_path(source, cache)


def test_when_the_index_in_use_is_out_of_date_the_error_says_what_to_do(
    source, tmp_path, monkeypatch
):
    cache = tmp_path / "cache"
    index.ensure(source, cache)
    touch_later(source)

    def refuse(*_):
        raise PermissionError("the file is in use")

    monkeypatch.setattr(index.os, "replace", refuse)
    with pytest.raises(BadDatabase, match="in use by another process"):
        index.ensure(source, cache)


def test_a_missing_source_is_reported_by_its_path(tmp_path):
    with pytest.raises(BadDatabase, match=r"missing\.sqlite does not exist"):
        index.ensure(tmp_path / "missing.sqlite", tmp_path / "cache")


def test_a_folder_is_not_a_source(tmp_path):
    with pytest.raises(BadDatabase, match="not a file"):
        index.ensure(tmp_path, tmp_path / "cache")


def test_a_file_that_is_not_sqlite_is_reported(tmp_path):
    junk = tmp_path / "junk.sqlite"
    junk.write_bytes(b"this is not a database" * 50)
    with pytest.raises(BadDatabase, match="cannot be read as a SQLite database"):
        index.ensure(junk, tmp_path / "cache")


def test_a_database_without_the_entries_table_is_reported(tmp_path):
    path = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE words (id INTEGER)")
    with pytest.raises(BadDatabase, match="has no `entries` table"):
        index.ensure(path, tmp_path / "cache")


def test_the_missing_columns_are_named(tmp_path):
    path = tmp_path / "thin.sqlite"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE entries (id INTEGER, headword TEXT, entry_text TEXT)")
    with pytest.raises(BadDatabase, match="homonym_index, start_column, start_page, volume"):
        index.ensure(path, tmp_path / "cache")


def test_an_empty_table_and_a_count_that_disagrees_with_the_metadata_are_reported(
    tmp_path, make_source, entries
):
    empty = make_source(tmp_path / "empty.sqlite", entries=[])
    with pytest.raises(BadDatabase, match="is empty"):
        index.ensure(empty, tmp_path / "cache")
    short = make_source(tmp_path / "short.sqlite", metadata={"entry_count": "45353"})
    with pytest.raises(BadDatabase, match=rf"holds {len(entries)} entries but .* says 45,353"):
        index.ensure(short, tmp_path / "cache")


def test_metadata_is_optional(tmp_path, make_source):
    source = make_source(tmp_path / "bare.sqlite", metadata={})
    assert index.title(index.ensure(source, tmp_path / "cache")) == index.DEFAULT_TITLE


def test_a_cache_folder_that_cannot_be_made_is_reported(tmp_path, source):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    with pytest.raises(BadDatabase, match="DICT_CACHE_DIR"):
        index.ensure(source, blocker / "cache")


def test_the_cache_folder_can_be_set(monkeypatch, tmp_path):
    monkeypatch.setenv("DICT_CACHE_DIR", str(tmp_path / "mine"))
    assert index.default_cache_dir() == tmp_path / "mine"


@pytest.mark.parametrize(
    ("platform", "env", "expected"),
    [
        ("win32", {"LOCALAPPDATA": "/data/local"}, "/data/local"),
        ("linux", {"XDG_CACHE_HOME": "/data/xdg"}, "/data/xdg"),
        ("linux", {}, "/home/me/.cache"),
        ("darwin", {}, "/home/me/Library/Caches"),
    ],
)
def test_the_default_cache_folder_follows_the_platform(monkeypatch, platform, env, expected):
    for name in ("DICT_CACHE_DIR", "LOCALAPPDATA", "XDG_CACHE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/me")))
    assert index.default_cache_dir() == Path(expected) / "azerbaijan-mcp" / "dict"
