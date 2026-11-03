import errno
import gzip
import hashlib
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from azerbaijan_mcp_dict import database
from azerbaijan_mcp_dict.errors import DownloadFailed

URL = "https://release.test/dict-1.sqlite.gz"
CUTS = ["empty", "inside-the-header", "header-only", "half", "last-byte-missing"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def data(asset_pack) -> bytes:
    return asset_pack.path.read_bytes()


def fetch(cache, site, sha256, **limits):
    return database.ensure(cache, url=URL, sha256=sha256, transport=site.transport, **limits)


def test_the_database_is_downloaded_checked_unpacked_and_kept(tmp_path, site, data, entries):
    server = site(lambda: httpx.Response(200, content=data))
    path = fetch(tmp_path, server, sha(data))
    assert path == tmp_path / f"dictionary-{sha(data)[:12]}.sqlite"
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT count(*) FROM entries").fetchone()[0] == len(entries)
    assert [p.name for p in tmp_path.iterdir()] == [path.name]  # no temporary file is left
    assert fetch(tmp_path, server, sha(data)) == path
    assert len(server.requests) == 1  # a kept database is not downloaded again


def test_the_request_says_who_makes_it(tmp_path, site, data):
    server = site(httpx.Response(200, content=data))
    fetch(tmp_path, server, sha(data))
    (request,) = server.requests
    assert (request.method, str(request.url)) == ("GET", URL)
    agent = request.headers["user-agent"]
    assert agent.startswith("azerbaijan-mcp-dict/")
    assert database.PROJECT_URL in agent


def test_a_redirect_is_followed(tmp_path, site, data):
    server = site(
        httpx.Response(302, headers={"location": "https://objects.release.test/x"}),
        httpx.Response(200, content=data),
    )
    assert fetch(tmp_path, server, sha(data)).is_file()
    assert [str(r.url) for r in server.requests] == [URL, "https://objects.release.test/x"]


def test_a_file_that_is_not_the_published_one_is_not_used(tmp_path, site, data):
    server = site(httpx.Response(200, content=b"something else"))
    with pytest.raises(DownloadFailed, match="does not match the published checksum"):
        fetch(tmp_path, server, sha(data))
    assert list(tmp_path.iterdir()) == []


def test_a_database_that_is_not_published_yet_says_so_and_how_to_go_on(tmp_path, site, data):
    server = site(httpx.Response(404))
    with pytest.raises(DownloadFailed, match=r"not published at .*\(HTTP 404\).*DICT_DB"):
        fetch(tmp_path, server, sha(data))
    assert len(server.requests) == 1


@pytest.mark.parametrize("status", [403, 429])
def test_a_site_that_refuses_is_asked_once(tmp_path, site, data, status):
    server = site(httpx.Response(status))
    with pytest.raises(DownloadFailed, match=rf"refuses the download \(HTTP {status}\)"):
        fetch(tmp_path, server, sha(data), retry_delay=0)
    assert len(server.requests) == 1


def test_a_server_error_is_tried_once_more(tmp_path, site, data):
    server = site(httpx.Response(503), lambda: httpx.Response(200, content=data))
    assert fetch(tmp_path, server, sha(data), retry_delay=0).is_file()
    assert len(server.requests) == 2
    broken = site(httpx.Response(500))
    with pytest.raises(DownloadFailed, match="HTTP 500"):
        fetch(tmp_path / "other", broken, sha(data), retry_delay=0)
    assert len(broken.requests) == 2


def test_a_network_error_is_tried_once_more(tmp_path, site, data):
    server = site(httpx.ConnectError("no route"), lambda: httpx.Response(200, content=data))
    assert fetch(tmp_path, server, sha(data), retry_delay=0).is_file()
    assert len(server.requests) == 2
    down = site(httpx.ConnectError("no route"))
    with pytest.raises(DownloadFailed, match="ConnectError: no route"):
        fetch(tmp_path / "other", down, sha(data), retry_delay=0)
    assert len(down.requests) == 2


def test_an_answer_over_the_ceiling_is_not_read(tmp_path, site, data):
    declared = site(httpx.Response(200, content=data))
    with pytest.raises(DownloadFailed, match="larger than 1,024 bytes"):
        fetch(tmp_path, declared, sha(data), max_bytes=1024)
    unannounced = site(httpx.Response(200, content=iter([b"x" * 600, b"x" * 600])))
    with pytest.raises(DownloadFailed, match="larger than 1,024 bytes"):
        fetch(tmp_path, unannounced, sha(b"x"), max_bytes=1024)
    assert list(tmp_path.iterdir()) == []


def test_a_file_that_is_not_gzip_is_not_used(tmp_path, site):
    junk = b"not a gzip file"
    with pytest.raises(DownloadFailed, match="not a valid gzip file"):
        fetch(tmp_path, site(httpx.Response(200, content=junk)), sha(junk))
    assert list(tmp_path.iterdir()) == []


def test_a_file_that_expands_beyond_the_ceiling_is_not_used(tmp_path, site):
    bomb = gzip.compress(b"\0" * 5_000_000)
    with pytest.raises(DownloadFailed, match="expands to more than 1 MB"):
        fetch(
            tmp_path, site(httpx.Response(200, content=bomb)), sha(bomb), max_database_bytes=2**20
        )
    assert list(tmp_path.iterdir()) == []


def test_only_https_addresses_are_used_but_this_computer_may_use_http(tmp_path, site, data):
    with pytest.raises(DownloadFailed, match="must start with https://"):
        database.ensure(tmp_path, url="http://release.test/x", sha256=sha(data))
    local = site(httpx.Response(200, content=data))
    path = database.ensure(
        tmp_path, url="http://127.0.0.1:8765/x.gz", sha256=sha(data), transport=local.transport
    )
    assert path.is_file()


def test_a_cache_folder_that_cannot_be_made_is_reported(tmp_path, site, data):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file, not a folder")
    with pytest.raises(DownloadFailed, match="DICT_CACHE_DIR"):
        fetch(blocker / "cache", site(httpx.Response(200, content=data)), sha(data))


def keep(tmp_path, data, content: bytes) -> Path:
    """Put `content` where the server keeps the database that `data` unpacks to."""
    target = tmp_path / f"dictionary-{sha(data)[:12]}.sqlite"
    target.write_bytes(content)
    return target


def test_when_another_process_kept_the_database_first_it_is_used(tmp_path, site, data, monkeypatch):
    whole = gzip.decompress(data)
    target = tmp_path / f"dictionary-{sha(data)[:12]}.sqlite"

    def other_process_wins(source, destination):
        target.write_bytes(whole)  # the other process's copy, all of it
        raise PermissionError("the file is in use")  # Windows will not replace an open file

    monkeypatch.setattr(database.os, "replace", other_process_wins)
    assert fetch(tmp_path, site(httpx.Response(200, content=data)), sha(data)) == target
    assert target.read_bytes() == whole
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_a_kept_database_that_is_whole_is_used_without_a_download(tmp_path, site, data):
    whole = gzip.decompress(data)
    target = keep(tmp_path, data, whole)
    server = site(httpx.Response(200, content=data))
    assert fetch(tmp_path, server, sha(data)) == target
    assert server.requests == []
    assert target.read_bytes() == whole


@pytest.mark.parametrize("how", CUTS)
def test_a_kept_database_that_was_cut_short_is_downloaded_again(tmp_path, site, data, cut_to, how):
    whole = gzip.decompress(data)
    target = keep(tmp_path, data, cut_to(whole, how))
    server = site(httpx.Response(200, content=data))
    assert fetch(tmp_path, server, sha(data)) == target
    assert target.read_bytes() == whole
    assert len(server.requests) == 1
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


def test_a_kept_file_that_is_not_sqlite_is_downloaded_again(tmp_path, site, data):
    whole = gzip.decompress(data)
    target = keep(tmp_path, data, b"x" * len(whole))  # the right size, the wrong content
    server = site(httpx.Response(200, content=data))
    assert fetch(tmp_path, server, sha(data)) == target
    assert target.read_bytes() == whole
    assert len(server.requests) == 1


def test_a_cut_short_database_is_copied_over_where_renames_are_refused(
    tmp_path, site, data, cut_to, renames_refused
):
    whole = gzip.decompress(data)
    target = keep(tmp_path, data, cut_to(whole, "half"))
    assert fetch(tmp_path, site(httpx.Response(200, content=data)), sha(data)) == target
    assert target.read_bytes() == whole
    assert [p.name for p in tmp_path.iterdir()] == [target.name]


def test_a_cut_short_database_that_another_process_holds_is_not_used(
    tmp_path, site, data, cut_to, monkeypatch
):
    whole = gzip.decompress(data)
    half = cut_to(whole, "half")
    target = keep(tmp_path, data, half)

    def in_use(*_, **__):
        raise PermissionError(errno.EACCES, "the file is in use")

    monkeypatch.setattr(database.os, "replace", in_use)
    with pytest.raises(DownloadFailed, match="Cannot write the dictionary database"):
        fetch(tmp_path, site(httpx.Response(200, content=data)), sha(data))
    assert target.read_bytes() == half  # theirs is left as it was


def test_a_database_that_cannot_be_written_is_reported_and_nothing_is_left(
    tmp_path, site, data, monkeypatch
):
    def denied(*_, **__):
        raise PermissionError(errno.EACCES, "Access is denied")  # and no other process has the file

    monkeypatch.setattr(database.os, "replace", denied)
    with pytest.raises(
        DownloadFailed, match=r"Cannot write the dictionary database in .*Access is denied"
    ):
        fetch(tmp_path, site(httpx.Response(200, content=data)), sha(data))
    assert list(tmp_path.iterdir()) == []


def test_where_renames_are_refused_the_database_is_copied_into_place(
    tmp_path, site, data, renames_refused
):
    server = site(httpx.Response(200, content=data))
    path = fetch(tmp_path, server, sha(data))
    assert path == tmp_path / f"dictionary-{sha(data)[:12]}.sqlite"
    assert path.read_bytes() == gzip.decompress(data)  # every byte of it, not just a readable file
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    assert [p.name for p in tmp_path.iterdir()] == [path.name]  # no temporary file is left
    assert fetch(tmp_path, server, sha(data)) == path
    assert len(server.requests) == 1  # a kept database is not downloaded again


@pytest.mark.parametrize(
    ("code", "reason"),
    [(errno.ENOSPC, "No space left on device"), (errno.EIO, "Input/output error")],
)
def test_a_rename_that_fails_for_another_reason_is_reported_and_leaves_nothing(
    tmp_path, site, data, monkeypatch, code, reason
):
    def fail(*_, **__):
        raise OSError(code, reason)

    monkeypatch.setattr(database.os, "replace", fail)
    with pytest.raises(
        DownloadFailed, match=rf"Cannot write the dictionary database in .*{reason}"
    ):
        fetch(tmp_path, site(httpx.Response(200, content=data)), sha(data))
    assert list(tmp_path.iterdir()) == []


def test_a_copy_that_fails_leaves_no_half_database(
    tmp_path, site, data, renames_refused, monkeypatch
):
    target = tmp_path / f"dictionary-{sha(data)[:12]}.sqlite"
    written = []

    def disk_fills_up(finished, out, *_):
        out.write(finished.read(64))
        out.flush()
        written.append(target.stat().st_size)  # a half database is there, under the final name
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(shutil, "copyfileobj", disk_fills_up)
    with pytest.raises(DownloadFailed, match="No space left on device"):
        fetch(tmp_path, site(httpx.Response(200, content=data)), sha(data))
    assert written == [64]
    assert list(tmp_path.iterdir()) == []


def test_the_pinned_address_and_checksum_have_the_shape_a_release_asset_needs():
    assert database.DATA_URL.startswith(
        "https://github.com/azerbaijan-mcp/azerbaijan-mcp/releases/"
    )
    assert len(database.DATA_SHA256) == 64
    assert set(database.DATA_SHA256) <= set("0123456789abcdef")
    assert 0 < database.DATA_SIZE < database.MAX_DOWNLOAD_BYTES
