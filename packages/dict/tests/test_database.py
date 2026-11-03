import gzip
import hashlib
import sqlite3
from contextlib import closing

import httpx
import pytest

from azerbaijan_mcp_dict import database
from azerbaijan_mcp_dict.errors import DownloadFailed

URL = "https://release.test/dict-1.sqlite.gz"


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


def test_when_another_process_kept_the_database_first_it_is_used(tmp_path, site, data, monkeypatch):
    target = tmp_path / f"dictionary-{sha(data)[:12]}.sqlite"

    def other_process_wins(source, destination):
        target.write_bytes(b"the other process's copy")
        raise PermissionError("the file is in use")  # Windows will not replace an open file

    monkeypatch.setattr(database.os, "replace", other_process_wins)
    assert fetch(tmp_path, site(httpx.Response(200, content=data)), sha(data)) == target
    assert sorted(p.name for p in tmp_path.iterdir()) == [target.name]


def test_the_pinned_address_and_checksum_have_the_shape_a_release_asset_needs():
    assert database.DATA_URL.startswith(
        "https://github.com/azerbaijan-mcp/azerbaijan-mcp/releases/"
    )
    assert len(database.DATA_SHA256) == 64
    assert set(database.DATA_SHA256) <= set("0123456789abcdef")
    assert 0 < database.DATA_SIZE < database.MAX_DOWNLOAD_BYTES
