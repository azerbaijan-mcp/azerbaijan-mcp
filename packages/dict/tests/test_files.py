import errno
import os
import shutil
import sqlite3
import stat
import string
import sys
import tempfile
from contextlib import closing
from pathlib import Path

import pytest

from azerbaijan_mcp_dict import files

PIECE = 1000  # the size the tests give the copy loop, so that a file takes several turns
PAGE_SIZES = [512, 1024, 4096, 32768, 65536]


def content(size: int) -> bytes:
    """Bytes that differ from place to place, so that a misplaced or a missing piece shows."""
    return bytes(i % 251 for i in range(size))


def make(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def never_copy(*_, **__):
    raise AssertionError("the file was copied although it could be renamed")


@pytest.fixture
def small_pieces(monkeypatch):
    monkeypatch.setattr(files, "CHUNK", PIECE)


@pytest.fixture
def finished(tmp_path) -> Path:
    return make(tmp_path / "finished.tmp", content(3 * PIECE + 17))


def test_a_file_is_renamed_into_place_when_the_system_allows_it(tmp_path, finished, monkeypatch):
    monkeypatch.setattr(shutil, "copyfileobj", never_copy)
    target = tmp_path / "final.sqlite"
    files.move_into_place(finished, target)
    assert target.read_bytes() == content(3 * PIECE + 17)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["final.sqlite"]  # renamed, not copied


def test_a_rename_replaces_the_file_that_is_there(tmp_path, finished, monkeypatch):
    monkeypatch.setattr(shutil, "copyfileobj", never_copy)
    target = make(tmp_path / "final.sqlite", b"old" * 5000)
    files.move_into_place(finished, target)
    assert target.read_bytes() == content(3 * PIECE + 17)


@pytest.mark.parametrize("size", [0, 1, PIECE - 1, PIECE, PIECE + 1, 5 * PIECE])
def test_where_renames_are_refused_the_file_is_copied_whole(
    tmp_path, renames_refused, small_pieces, size
):
    source = make(tmp_path / "finished.tmp", content(size))
    target = tmp_path / "final.sqlite"
    files.move_into_place(source, target)
    assert target.read_bytes() == content(size)
    assert source.read_bytes() == content(size)  # left for its owner to delete
    assert sorted(p.name for p in tmp_path.iterdir()) == ["final.sqlite", "finished.tmp"]


def test_a_copy_replaces_a_longer_file_without_keeping_its_tail(
    tmp_path, finished, renames_refused, small_pieces
):
    target = make(tmp_path / "final.sqlite", b"old" * 5000)  # 15,000 bytes against 3,017
    files.move_into_place(finished, target)
    assert target.read_bytes() == content(3 * PIECE + 17)


def test_a_copy_goes_by_the_piece_and_not_all_at_once(
    tmp_path, finished, renames_refused, small_pieces, monkeypatch
):
    lengths = []
    real = shutil.copyfileobj

    def spy(source, out, length):
        lengths.append(length)
        real(source, out, length)

    monkeypatch.setattr(shutil, "copyfileobj", spy)
    files.move_into_place(finished, tmp_path / "final.sqlite")
    assert lengths == [PIECE]


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(errno.EACCES, "Access is denied"),
        FileNotFoundError(errno.ENOENT, "The system cannot find the path specified"),
        OSError(errno.ENOSPC, "No space left on device"),
        OSError(errno.EIO, "Input/output error"),
        OSError("an error with no code"),
    ],
    ids=["in-use", "missing-folder", "disk-full", "io-error", "no-code"],
)
def test_any_other_error_is_raised_as_it_is_and_nothing_is_copied(
    tmp_path, finished, monkeypatch, error
):
    def refuse(*_, **__):
        raise error

    monkeypatch.setattr(os, "replace", refuse)
    monkeypatch.setattr(shutil, "copyfileobj", never_copy)
    target = make(tmp_path / "final.sqlite", b"what was there")
    with pytest.raises(OSError) as raised:
        files.move_into_place(finished, target)
    assert raised.value is error
    assert target.read_bytes() == b"what was there"
    assert finished.read_bytes() == content(3 * PIECE + 17)


@pytest.mark.parametrize("old", [None, b"what was there"], ids=["no-old-file", "old-file"])
def test_a_copy_that_fails_halfway_leaves_nothing_under_the_final_name(
    tmp_path, finished, renames_refused, small_pieces, monkeypatch, old
):
    target = tmp_path / "final.sqlite"
    if old is not None:
        make(target, old)
    written = []

    def disk_fills_up(source, out, length):
        out.write(source.read(length))
        out.flush()
        written.append(target.stat().st_size)  # half a file is there, under the final name
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copyfileobj", disk_fills_up)
    with pytest.raises(OSError) as raised:
        files.move_into_place(finished, target)
    assert raised.value.errno == errno.ENOSPC
    assert written == [PIECE]
    assert not target.exists()
    assert finished.read_bytes() == content(3 * PIECE + 17)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["finished.tmp"]


def test_an_interrupted_copy_leaves_nothing_either(
    tmp_path, finished, renames_refused, small_pieces, monkeypatch
):
    target = tmp_path / "final.sqlite"

    def interrupted(source, out, length):
        out.write(source.read(length))
        out.flush()
        raise KeyboardInterrupt

    monkeypatch.setattr(shutil, "copyfileobj", interrupted)
    with pytest.raises(KeyboardInterrupt):
        files.move_into_place(finished, target)
    assert not target.exists()


def test_a_file_that_cannot_be_written_is_left_as_it_was(tmp_path, finished, renames_refused):
    target = make(tmp_path / "final.sqlite", b"in use")
    target.chmod(stat.S_IREAD)  # a read-only file; on Windows this is the attribute
    try:
        try:
            with target.open("ab"):
                pass
        except PermissionError:
            pass
        else:
            pytest.skip("this account can write to read-only files")
        with pytest.raises(PermissionError):
            files.move_into_place(finished, target)
        assert target.read_bytes() == b"in use"
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_a_source_that_is_gone_is_an_error_and_the_old_file_stays(tmp_path, renames_refused):
    target = make(tmp_path / "final.sqlite", b"old")
    with pytest.raises(FileNotFoundError):
        files.move_into_place(tmp_path / "gone.tmp", target)
    assert target.read_bytes() == b"old"


def make_database(path: Path, *, page_size: int = 4096, journal: str = "delete") -> Path:
    """A real SQLite file of several pages, written by SQLite."""
    rows = 4 * page_size // 100 + 100
    with closing(sqlite3.connect(path)) as db:
        db.execute(f"PRAGMA page_size = {page_size}")
        db.execute(f"PRAGMA journal_mode = {journal}")
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, body TEXT)")
        with db:
            db.executemany(
                "INSERT INTO t (body) VALUES (?)", [("x" * 100 + str(n),) for n in range(rows)]
            )
    return path


@pytest.mark.parametrize("page_size", PAGE_SIZES)
def test_a_whole_database_is_whole_whatever_its_page_size(tmp_path, page_size):
    path = make_database(tmp_path / "db.sqlite", page_size=page_size)
    assert path.stat().st_size // page_size >= 4  # several pages, so that the cuts below are cuts
    assert files.is_whole_sqlite(path)


@pytest.mark.parametrize("page_size", PAGE_SIZES)
def test_a_database_cut_anywhere_is_not_whole(tmp_path, page_size):
    whole = make_database(tmp_path / "db.sqlite", page_size=page_size).read_bytes()
    pages = len(whole) // page_size
    sizes = {0, 1, 15, 16, 99, 100, 101, page_size - 1, page_size, page_size + 1, len(whole) - 1}
    sizes |= {n * page_size for n in range(pages)} | {
        n * page_size - 1 for n in range(1, pages + 1)
    }
    cut = tmp_path / "cut.sqlite"
    for size in sorted(s for s in sizes if 0 <= s < len(whole)):
        cut.write_bytes(whole[:size])
        assert not files.is_whole_sqlite(cut), f"cut at {size} of {len(whole)} bytes is whole"


def test_a_database_with_room_after_its_last_page_is_still_whole(tmp_path):
    path = make_database(tmp_path / "db.sqlite")
    path.write_bytes(path.read_bytes() + b"\0" * 10_000)  # a file that was grown in chunks
    assert files.is_whole_sqlite(path)


def test_a_database_in_wal_mode_is_whole(tmp_path):
    path = make_database(tmp_path / "wal.sqlite", journal="wal")
    assert [p.name for p in tmp_path.iterdir()] == ["wal.sqlite"]  # the log was folded in
    assert files.is_whole_sqlite(path)


@pytest.mark.parametrize("how", ["counter-moved-on", "count-is-zero"])
def test_a_page_count_that_is_not_current_is_not_trusted(tmp_path, how):
    whole = bytearray(make_database(tmp_path / "db.sqlite").read_bytes())
    if how == "counter-moved-on":  # a change that the page count in the header does not know of
        whole[24:28] = (int.from_bytes(whole[24:28], "big") + 1).to_bytes(4, "big")
    else:
        whole[28:32] = bytes(4)
    path = tmp_path / "unsure.sqlite"
    path.write_bytes(bytes(whole))
    assert files.is_whole_sqlite(path)
    path.write_bytes(bytes(whole[: len(whole) // 2]))
    assert files.is_whole_sqlite(path)  # no count to hold it to, so its first page is all it needs
    path.write_bytes(bytes(whole[:200]))
    assert not files.is_whole_sqlite(path)  # not even one page


def test_a_file_that_is_not_sqlite_is_not_whole(tmp_path):
    whole = make_database(tmp_path / "db.sqlite").read_bytes()
    other_version = b"SQLite format 4\x00" + whole[16:]
    path = tmp_path / "other"
    for what, content in {
        "empty": b"",
        "text": b"x" * len(whole),
        "zeros": bytes(len(whole)),
        "another magic": other_version,
    }.items():
        path.write_bytes(content)
        assert not files.is_whole_sqlite(path), what


@pytest.mark.parametrize("page", [0, 100, 511, 513, 3000, 65535])
def test_a_header_with_an_impossible_page_size_is_not_whole(tmp_path, page):
    whole = bytearray(make_database(tmp_path / "db.sqlite").read_bytes())
    whole[16:18] = page.to_bytes(2, "big")
    path = tmp_path / "odd.sqlite"
    path.write_bytes(bytes(whole))
    assert not files.is_whole_sqlite(path)


def test_a_missing_file_and_a_folder_are_not_whole(tmp_path):
    assert not files.is_whole_sqlite(tmp_path / "nothing")
    assert not files.is_whole_sqlite(tmp_path)


def fixed_drives() -> list[Path]:
    import ctypes

    drive_type = ctypes.windll.kernel32.GetDriveTypeW  # type: ignore[attr-defined]
    roots = [Path(f"{letter}:\\") for letter in string.ascii_uppercase]
    return [root for root in roots if root.exists() and drive_type(str(root)) == 3]


def folder_on_another_device(here: Path) -> Path | None:
    """A new folder on a different file system than `here`, or None if there is none to write to."""
    roots = fixed_drives() if sys.platform == "win32" else [Path("/dev/shm")]
    for root in roots:
        try:
            folder = Path(tempfile.mkdtemp(dir=root))
        except OSError:
            continue
        if folder.stat().st_dev != here.stat().st_dev:
            return folder
        shutil.rmtree(folder, ignore_errors=True)
    return None


def test_a_real_rename_across_devices_is_copied(tmp_path, finished):
    folder = folder_on_another_device(tmp_path)
    if folder is None:
        pytest.skip("this computer has no other file system to write to")
    try:
        probe = make(tmp_path / "probe.tmp", b"probe")
        with pytest.raises(OSError) as refused:  # the system really does refuse, so this is no fake
            os.replace(probe, folder / "probe")
        assert refused.value.errno == errno.EXDEV
        target = folder / "final.sqlite"
        files.move_into_place(finished, target)
        assert target.read_bytes() == content(3 * PIECE + 17)
        assert finished.read_bytes() == content(3 * PIECE + 17)
        assert sorted(p.name for p in folder.iterdir()) == ["final.sqlite"]
    finally:
        shutil.rmtree(folder, ignore_errors=True)
