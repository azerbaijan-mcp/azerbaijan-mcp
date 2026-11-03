"""Contract tests against the real dictionary database. Run them with the database's path:

    DICT_DB=path/to/azerbaycan_lugeti_1-4.sqlite uv run pytest -m live packages/dict

Those that need the database are skipped when DICT_DB is not set. The index goes to a temporary
folder, and the database itself is opened read-only. The numbers are those of the four-volume
dictionary. The last test uses the network: it downloads the published database, as a user's
first call does.
"""

import os
from contextlib import closing
from pathlib import Path

import pytest

from azerbaijan_mcp_dict import files, index
from azerbaijan_mcp_dict.store import Store

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    path = os.environ.get("DICT_DB", "").strip()
    if not path:
        pytest.skip("set DICT_DB to the real dictionary database to run these tests")
    source = Path(path)
    before = (source.stat().st_size, source.stat().st_mtime_ns)
    store = Store(source, tmp_path_factory.mktemp("index"))
    store.define("su", 100)  # builds the index
    yield store
    after = source.stat()
    assert (after.st_size, after.st_mtime_ns) == before, "the database must not be touched"


def headwords(entries) -> list[str]:
    return [entry.headword for entry in entries]


def test_the_index_has_every_entry_of_the_four_volumes(real):
    with closing(index.connect(index.ensure(real._source, real._cache))) as db:
        count, volumes = db.execute("SELECT count(*), count(DISTINCT volume) FROM entry").fetchone()
        newlines = db.execute("SELECT count(*) FROM entry WHERE text LIKE '%' || char(10) || '%'")
        spaced = db.execute("SELECT count(*) FROM entry WHERE text LIKE '%b a x%'")
        assert (newlines.fetchone()[0], spaced.fetchone()[0]) == (0, 0)
    assert count >= 40_000
    assert volumes == 4


def test_common_words_are_defined_and_homonyms_come_apart(real):
    assert headwords(real.define("su", 500).entries) == ["SU"]
    assert headwords(real.define("çay", 500).entries) == ["ÇAY¹", "ÇAY²"]
    assert real.define("seher", 500).match == "accent_free"
    assert {"SƏHƏR", "ŞƏHƏR"} <= set(headwords(real.define("seher", 500).entries))


def test_a_variant_headword_is_found_under_each_spelling(real):
    assert headwords(real.define("abbası", 500).entries) == ["AB(B)ASI"]
    assert headwords(real.define("abası", 500).entries) == ["AB(B)ASI"]


def test_a_pointer_leads_to_the_entry_it_names(real):
    out = real.define("baxım", 500)
    assert "BAXIŞ" in headwords(out.followed)


def test_the_inflected_form_gets_its_stem_suggested(real):
    out = real.define("kitabları", 500)
    assert out.match == "none"
    assert out.suggestions[0] == "KİTAB"


def test_search_finds_the_words_the_database_own_index_misses(real):
    # The database's FTS index finds 1,324 of the 1,656 entries that have "iki" as a word,
    # because it does not fold a capital İ at the start of a sentence.
    out = real.search("iki", 5, 0, False)
    assert out.count >= 1_650
    assert out.results[0].headword == "İKİ"


def test_browse_walks_the_alphabet(real):
    out = real.browse("kitab", None, 0, 12)
    names = headwords_of(out)
    assert names[0] == "KİTAB"
    assert "KİTABXANA" in names


def headwords_of(browse) -> list[str]:
    return [entry.headword for entry in browse.entries]


def test_the_longest_entries_can_be_read_to_the_end(real):
    with closing(index.connect(index.ensure(real._source, real._cache))) as db:
        entry_id, length = db.execute(
            "SELECT id, length(text) FROM entry ORDER BY length(text) DESC LIMIT 1"
        ).fetchone()
    assert length > 20_000
    pieces, offset = [], 0
    while offset is not None:
        page = real.read_entry(entry_id, offset, 5000)
        pieces.append(page.text)
        offset = page.next_offset
    assert sum(len(piece) for piece in pieces) + len(pieces) - 1 == length


def test_the_published_database_downloads_is_checked_and_answers(tmp_path):
    out = Store(None, tmp_path).define("kitab", 200)
    assert [entry.headword for entry in out.entries] == ["KİTAB"]
    (kept,) = tmp_path.glob("dictionary-*.sqlite")
    (built,) = tmp_path.glob("index-*.sqlite")
    # the check that spots a copy cut short must never judge the real database or its index so
    assert files.is_whole_sqlite(kept)
    assert files.is_whole_sqlite(built)
    server = Store(None, tmp_path)  # a new process: both are kept, so nothing is fetched or built
    assert [entry.headword for entry in server.define("kitab", 200).entries] == ["KİTAB"]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([kept.name, built.name])
