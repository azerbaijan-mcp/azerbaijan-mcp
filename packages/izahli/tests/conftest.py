"""Shared fixtures. Every dictionary entry here is invented for the tests, in the layout of the real
dictionary (labels, line breaks, "bax" pointers); none of them is a line of the real one."""

import socket
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import httpx
import pytest

from azerbaijan_mcp_izahli import asset, index
from azerbaijan_mcp_izahli.store import Store

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
TITLE = "Invented test dictionary"

# headword, homonym number, text as the PDF gives it (lines broken), volume, PDF page, column
Entry = tuple[str, int | None, str, int, int, int]

LONG_TEXT = "f. " + " ".join(
    f"{n}. Bu sözün {n}-ci mənasının izahı və nümunəsi." for n in range(300)
)

ENTRIES: list[Entry] = [
    ("ACGÖZ(LÜ)", None, "sif. Doymaq bilməyən, həris. Acgöz adam heç nəyə qane olmur.", 1, 26, 1),
    ("ADLIQ:", None, "is. Ad daşıyan şey.", 1, 26, 2),
    ("AĞÇA", None, "sif. Ağa çalan, ağımtıl rəngli. Ağça paltar.", 1, 27, 1),
    ("ATA-BABA", None, "is. Əcdad, keçmiş nəsillər. Ata-\nbaba torpağı əziz tutulur.", 1, 27, 1),
    ("AXÇA", None, "b a x ağça.", 1, 27, 2),
    ("BAXIM", None, "is. bax baxış 1-ci mənada. Bu baxımdan fikir düzgündür.", 1, 28, 1),
    (
        "BAXIŞ",
        None,
        "is. 1. Nəzər, göz gəzdirmə. Sərt baxış.\n2. Fikir, münasibət. Dünyaya baxış.",
        1,
        28,
        1,
    ),
    ("ÇAY", 1, "is. [çin.] Qurudulmuş yarpaqdan hazırlanan içki. Çay\nsüzdü.", 1, 29, 1),
    ("ÇAY", 2, "is. Kiçik axar su. Çay sahilində oturduq.", 1, 29, 1),
    ("ÇAYLIQ", None, "is. bax çay2 sözünə.", 1, 29, 2),
    ("EL", None, "is. Xalq, camaat. El ağzında dolaşan söz.", 2, 5, 1),
    ("ƏL", None, "is. Qolun barmaqlarla bitən hissəsi. İki əlini uzatdı.", 2, 5, 2),
    ("İKİ", None, "say. Birdən sonra gələn say. İki dost yolda görüşdü.", 2, 6, 1),
    ("İŞIQ", None, "is. Görməyə imkan verən parlaqlıq. İşıq otağı doldurdu.", 2, 6, 1),
    (
        "KİTAB",
        None,
        "is. [ər.] Yazılı və ya çap olunmuş səhifələrdən ibarət cild. Kitab oxumaq xoşdur.",
        2,
        7,
        1,
    ),
    ("KİTABÇA", None, "is. Kiçik kitab, bukləd. □ Cib kitabçası \u2013 bax kitab.", 2, 7, 1),
    (
        "KİTABXANA",
        None,
        "is. Kitab saxlanılan və oxuculara verilən yer. Kitab-\nxana səssiz idi.",
        2,
        7,
        2,
    ),
    ("OLMAQ", None, LONG_TEXT, 3, 8, 1),
    ("SƏHƏR", None, "is. 1. Gecənin sonu. 2. Səhər yeməyi. Səhər tezdən qalxdım.", 4, 9, 1),
    ("SU", None, "is. Rəngsiz və qoxusuz maye. Su içmək. Su qabı doldu.", 4, 9, 2),
    ("ŞƏHƏR", None, "is. Böyük yaşayış məntəqəsi. Şəhər işıqlarla dolu idi.", 4, 10, 1),
]

# The real database also has columns the server must not rely on; these carry a decoy.
SOURCE_SCHEMA = """
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    volume INTEGER NOT NULL CHECK(volume BETWEEN 1 AND 4),
    headword TEXT NOT NULL,
    headword_normalized TEXT NOT NULL,
    headword_search TEXT NOT NULL,
    homonym_index INTEGER,
    display_headword TEXT NOT NULL,
    entry_text TEXT NOT NULL,
    search_text TEXT NOT NULL,
    start_page INTEGER NOT NULL,
    end_page INTEGER NOT NULL,
    start_column INTEGER NOT NULL CHECK(start_column IN (1, 2))
);
"""
DECOY = "THE SERVER MUST NOT READ THIS COLUMN"


def write_source(
    path: Path,
    entries: Sequence[Entry] = ENTRIES,
    metadata: Mapping[str, str] | None = None,
) -> Path:
    """Write a source database in the shape of the real one."""
    if metadata is None:
        metadata = {"database_title": TITLE, "entry_count": str(len(entries))}
    db = sqlite3.connect(path)
    with db:
        db.executescript(SOURCE_SCHEMA)
        for number, (headword, homonym, text, volume, page, column) in enumerate(entries, 1):
            row = (number, volume, headword, DECOY, DECOY, homonym, DECOY, text, DECOY)
            db.execute(
                "INSERT INTO entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*row, page, page, column),
            )
        db.executemany("INSERT INTO metadata VALUES (?, ?)", metadata.items())
    db.close()
    return path


def _host(address) -> str:
    return address[0] if isinstance(address, tuple) else str(address)


@pytest.fixture(autouse=True, scope="module")
def no_network(request):
    """Offline tests never reach the real release page: outside connections fail at once.

    Loopback stays open because asyncio itself connects a pair of local sockets on Windows.
    """
    if request.node.get_closest_marker("live"):  # the live tests may use the real network
        yield
        return
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def connect(self, address):
        if _host(address) not in LOCAL_HOSTS:
            raise RuntimeError(f"network access is blocked in these tests: {_host(address)}")
        return real_connect(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host not in LOCAL_HOSTS and host is not None:
            raise RuntimeError(f"network access is blocked in these tests: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    patch = pytest.MonkeyPatch()
    patch.setattr(socket.socket, "connect", connect)
    patch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    patch.undo()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="session")
def entries() -> list[Entry]:
    return ENTRIES


@pytest.fixture(scope="session")
def title() -> str:
    return TITLE


@pytest.fixture(scope="session")
def make_source() -> Callable[..., Path]:
    return write_source


@pytest.fixture
def count_builds(monkeypatch) -> list[Path]:
    """Counts the index builds: the list gets the source path of each one."""
    builds: list[Path] = []
    real = index._build

    def build(source, target, stamp):
        builds.append(source)
        real(source, target, stamp)

    monkeypatch.setattr(index, "_build", build)
    return builds


@pytest.fixture(scope="session")
def source_db(tmp_path_factory) -> Path:
    return write_source(tmp_path_factory.mktemp("source") / "dictionary.sqlite")


@pytest.fixture(scope="session")
def cache_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("cache")


class Site:
    """A fake release page. It answers the requests it gets with the answers it was given, in
    turn and the last one for ever, and keeps the requests. An answer is a response, an error to
    raise, or a function that makes a fresh response."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(answer, Exception):
            raise answer
        return answer if isinstance(answer, httpx.Response) else answer()

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


@pytest.fixture
def site() -> type[Site]:
    return Site


@pytest.fixture(scope="session")
def asset_pack(source_db: Path, tmp_path_factory) -> asset.Packed:
    """The invented dictionary, packed the way the real one is published."""
    return asset.pack(source_db, tmp_path_factory.mktemp("asset") / "dictionary.sqlite.gz")


@pytest.fixture(scope="session")
def store(source_db: Path, cache_dir: Path) -> Store:
    """A store over the invented dictionary. Tests only read, so one index serves them all."""
    return Store(source_db, cache_dir)
