import shutil
from concurrent.futures import ThreadPoolExecutor

import pytest

from azerbaijan_mcp_izahli import store as store_module
from azerbaijan_mcp_izahli.errors import BadDatabase, BadQuery, NotConfigured, NotFound
from azerbaijan_mcp_izahli.store import Store

# Ids follow print order: KİTAB is 15, its neighbours İŞIQ 14 and KİTABÇA 16, AXÇA 5, AĞÇA 3.


def headwords(entries) -> list[str]:
    return [entry.headword for entry in entries]


def ref(entry_id: int, headword: str) -> dict:
    return {"id": entry_id, "headword": headword}


def small_store(tmp_path, make_source, pairs) -> Store:
    """A store over entries that are only a headword and a text, for pointer chains."""
    entries = [(headword, None, text, 1, 26, 1) for headword, text in pairs]
    return Store(make_source(tmp_path / "small.sqlite", entries), tmp_path / "cache")


# -- define


def test_define_returns_the_entry_with_where_it_stands_in_the_volumes(store, title):
    out = store.define("kitab", 3000)
    assert (out.query, out.match) == ("kitab", "exact")
    assert headwords(out.entries) == ["KİTAB"]
    (entry,) = out.entries
    assert entry.id == 15
    assert entry.origin == "ər."
    assert entry.text == (
        "is. [ər.] Yazılı və ya çap olunmuş səhifələrdən ibarət cild. Kitab oxumaq xoşdur."
    )
    assert (entry.volume, entry.pdf_page, entry.column) == (2, 7, 1)
    assert (entry.total_chars, entry.offset, entry.next_offset) == (len(entry.text), 0, None)
    assert (out.followed, out.suggestions, out.notes) == ([], [], [])
    assert out.source == title
    assert title in out.attribution
    assert "machine extraction" in out.attribution


@pytest.mark.parametrize("typed", ["kitab", "KİTAB", "Kitab", "  kitab! ", "«kitab»"])
def test_case_and_punctuation_do_not_matter(store, typed):
    out = store.define(typed, 3000)
    assert (out.match, headwords(out.entries)) == ("exact", ["KİTAB"])


def test_the_dotless_capital_i_is_not_the_dotted_one(store):
    out = store.define("KITAB", 3000)  # an ASCII capital I is ı, so only accent-free finds it
    assert (out.match, headwords(out.entries)) == ("accent_free", ["KİTAB"])
    assert "match once accents and hyphens are ignored" in out.notes[0]


def test_homonyms_are_separate_entries_in_print_order(store):
    out = store.define("çay", 3000)
    assert headwords(out.entries) == ["ÇAY¹", "ÇAY²"]
    assert out.entries[0].origin == "çin."
    assert out.entries[1].origin is None
    assert headwords(store.define("ÇAY²", 3000).entries) == ["ÇAY¹", "ÇAY²"]


def test_the_colon_the_extraction_leaves_on_a_headword_is_not_shown(store):
    assert headwords(store.define("adlıq", 3000).entries) == ["ADLIQ"]


@pytest.mark.parametrize("typed", ["acgöz", "acgözlü", "ACGÖZLÜ", "ACGÖZ(LÜ)", "acgöz(lü)"])
def test_each_spelling_of_a_variant_headword_finds_it(store, typed):
    out = store.define(typed, 3000)
    assert (out.match, headwords(out.entries)) == ("exact", ["ACGÖZ(LÜ)"])


def test_a_word_spelled_without_accents_finds_every_word_it_could_be(store):
    out = store.define("seher", 3000)
    assert out.match == "accent_free"
    assert headwords(out.entries) == ["SƏHƏR", "ŞƏHƏR"]


@pytest.mark.parametrize(("typed", "found"), [("el", "EL"), ("əl", "ƏL"), ("EL", "EL")])
def test_an_exact_spelling_beats_the_same_word_without_accents(store, typed, found):
    out = store.define(typed, 3000)
    assert (out.match, headwords(out.entries)) == ("exact", [found])


def test_hyphens_may_be_left_out_or_typed_as_a_space(store):
    assert store.define("atababa", 3000).match == "accent_free"
    assert headwords(store.define("atababa", 3000).entries) == ["ATA-BABA"]
    spaced = store.define("ata baba", 3000)
    assert (spaced.match, headwords(spaced.entries)) == ("exact", ["ATA-BABA"])


@pytest.mark.parametrize(
    ("typed", "match", "found"),
    [
        ("ata\u2013baba", "exact", "ATA-BABA"),  # an en dash
        ("ata\u2011baba", "exact", "ATA-BABA"),  # a non-breaking hyphen
        ("ata\u00adbaba", "accent_free", "ATA-BABA"),  # a soft hyphen is invisible
        ("\u2018kitab\u2019", "exact", "KİTAB"),  # curly quotes
        ("kit\u200bab", "exact", "KİTAB"),  # a zero-width space
        ("i\u0307ki", "exact", "İKİ"),  # i and a combining dot, which is what lower() makes of İ
        ("kitab1", "exact", "KİTAB"),  # the homonym number, as a pointer prints it
        ("çay2", "exact", "ÇAY¹"),  # every homonym comes back
    ],
)
def test_the_ways_a_word_gets_typed_find_it(store, typed, match, found):
    out = store.define(typed, 3000)
    assert (out.match, out.entries[0].headword) == (match, found)


def test_a_headword_typed_as_printed_is_found_by_define_browse_and_search(tmp_path, make_source):
    printed = small_store(
        tmp_path,
        make_source,
        [
            ("AB(B)ASI", "is. A coin."),
            ("AB-HAVA,ABÜHAVA", "is. Weather."),
            ("RAD[D]Ə", "is. A step."),
        ],
    )
    for typed, shown in [
        ("AB(B)ASI", "AB(B)ASI"),
        ("abası", "AB(B)ASI"),
        ("abbası", "AB(B)ASI"),
        ("AB-HAVA, ABÜHAVA", "AB-HAVA, ABÜHAVA"),
        ("abühava", "AB-HAVA, ABÜHAVA"),
        ("RAD[D]Ə", "RAD[D]Ə"),
        ("radə", "RAD[D]Ə"),
        ("raddə", "RAD[D]Ə"),
    ]:
        out = printed.define(typed, 500)
        assert (out.match, headwords(out.entries)) == ("exact", [shown])
    assert [n.headword for n in printed.browse("AB(B)ASI", None, 0, 0).entries] == ["AB(B)ASI"]
    assert printed.search("AB(B)ASI", 5, 0, False).count == 1


def test_the_highest_code_point_is_just_not_found(store):
    assert store.define("\U0010ffff", 500).match == "none"
    with pytest.raises(NotFound):
        store.browse("\U0010ffff", None, 1, 1)


def test_the_lines_of_an_entry_are_joined_and_real_hyphens_stay(store):
    assert store.define("ata-baba", 3000).entries[0].text == (
        "is. Əcdad, keçmiş nəsillər. Ata-baba torpağı əziz tutulur."
    )
    assert store.define("kitabxana", 3000).entries[0].text.endswith("Kitabxana səssiz idi.")
    assert store.define("çay", 3000).entries[0].text.endswith("Çay süzdü.")
    assert store.define("baxış", 3000).entries[0].text == (
        "is. 1. Nəzər, göz gəzdirmə. Sərt baxış. 2. Fikir, münasibət. Dünyaya baxış."
    )


def test_an_entry_that_only_points_comes_with_the_entry_it_points_to(store):
    out = store.define("axça", 3000)
    (entry,) = out.entries
    assert entry.text == "bax ağça."  # the letter-spaced "b a x" of the PDF is one word again
    assert [see.model_dump() for see in entry.see] == [
        {"pointer": "ağça", "entries": [ref(3, "AĞÇA")]}
    ]
    (followed,) = out.followed
    assert (followed.headword, followed.via) == ("AĞÇA", entry.id)
    assert followed.text.startswith("sif. Ağa çalan")


def test_a_pointer_to_a_numbered_sense_leads_to_the_headword(store):
    out = store.define("baxım", 3000)
    assert [see.pointer for see in out.entries[0].see] == ["baxış 1-ci mənada"]
    assert [(entry.headword, entry.via) for entry in out.followed] == [("BAXIŞ", 6)]


def test_a_pointer_with_a_homonym_number_leads_to_that_homonym_only(store):
    out = store.define("çaylıq", 3000)
    assert [see.model_dump() for see in out.entries[0].see] == [
        {"pointer": "çay2 sözünə", "entries": [ref(9, "ÇAY²")]}
    ]
    assert [(entry.headword, entry.via) for entry in out.followed] == [("ÇAY²", 10)]


def test_a_pointer_inside_an_entry_is_listed_but_not_followed(store):
    out = store.define("kitabça", 3000)
    assert [see.model_dump() for see in out.entries[0].see] == [
        {"pointer": "kitab", "entries": [ref(15, "KİTAB")]}
    ]
    assert out.followed == []


def test_pointers_are_followed_two_steps_at_most(tmp_path, make_source):
    chain = small_store(
        tmp_path,
        make_source,
        [("AAA", "bax bbb."), ("BBB", "bax ccc."), ("CCC", "bax ddd."), ("DDD", "is. The end.")],
    )
    assert [(f.headword, f.via) for f in chain.define("aaa", 3000).followed] == [
        ("BBB", 1),
        ("CCC", 2),
    ]


def test_pointers_that_lead_back_do_not_loop(tmp_path, make_source):
    loop = small_store(tmp_path, make_source, [("XXX", "bax yyy."), ("YYY", "bax xxx.")])
    assert [(f.headword, f.via) for f in loop.define("xxx", 3000).followed] == [("YYY", 1)]


def test_a_word_that_is_not_a_headword_gets_its_stem_suggested(store):
    out = store.define("kitabları", 3000)
    assert (out.match, out.entries, out.followed) == ("none", [], [])
    assert out.suggestions == ["KİTAB"]
    assert out.notes[0] == "No headword matches 'kitabları'."
    assert "base forms" in out.notes[1]


def test_a_misspelt_word_gets_the_word_it_is_close_to(store):
    assert store.define("kitba", 3000).suggestions == ["KİTAB"]


def test_a_phrase_is_pointed_to_search(store):
    out = store.define("su içmək", 3000)
    assert out.match == "none"
    assert "single words" in out.notes[1]


def test_nothing_close_gives_no_suggestions(store):
    out = store.define("zzzzzz", 3000)
    assert out.match == "none"
    assert (out.suggestions, out.notes) == ([], ["No headword matches 'zzzzzz'."])


def test_a_word_made_only_of_punctuation_is_a_bad_query(store):
    with pytest.raises(BadQuery, match="Give the word"):
        store.define("...", 3000)


def test_a_long_entry_is_cut_and_read_on_with_read_entry(store):
    out = store.define("olmaq", 300)
    (entry,) = out.entries
    assert len(entry.text) <= 300
    assert entry.next_offset is not None
    assert "read_entry" in out.notes[-1]
    whole = store.read_entry(entry.id, 0, 50000)
    assert whole.next_offset is None
    assert whole.total_chars == entry.total_chars == len(whole.text)
    pieces, offset = [], 0
    while offset is not None:
        page = store.read_entry(entry.id, offset, 500)
        pieces.append(page.text)
        offset = page.next_offset
    assert len(pieces) > 5
    assert " ".join(pieces) == whole.text


def test_no_more_than_the_limit_of_entries_is_shown(store, monkeypatch):
    monkeypatch.setattr(store_module, "MAX_ENTRIES", 1)
    out = store.define("çay", 3000)
    assert headwords(out.entries) == ["ÇAY¹"]
    assert out.notes == ["2 entries match; the first 1 are shown."]


# -- read_entry


def test_read_entry_gives_the_pointers_of_the_piece_it_returns(store):
    page = store.read_entry(5, 0, 3000)
    assert page.headword == "AXÇA"
    assert [see.pointer for see in page.see] == ["ağça"]
    assert page.source and page.attribution


def test_an_entry_that_does_not_exist_is_not_found(store):
    with pytest.raises(NotFound, match="No entry has id 999"):
        store.read_entry(999, 0, 500)


def test_reading_past_the_end_gives_nothing_and_says_so(store):
    page = store.read_entry(15, 5000, 500)
    assert (page.text, page.next_offset) == ("", None)
    assert "past the end" in page.notes[0]


# -- search


def test_search_finds_words_that_start_a_sentence_with_a_capital_i(store):
    out = store.search("iki", 10, 0, False)
    # the headword first, then the entry that only has "İki" at the start of a sentence
    assert (out.count, headwords(out.results)) == (2, ["İKİ", "ƏL"])
    assert out.results[1].snippet == "is. Qolun barmaqlarla bitən hissəsi. İki əlini uzatdı."
    assert [hit.id for hit in store.search("İKİ", 10, 0, False).results] == [13, 12]


def test_search_matches_the_first_five_letters_of_a_long_word_unless_exact(store):
    out = store.search("işıq", 10, 0, False)
    assert (out.count, headwords(out.results)) == (2, ["İŞIQ", "ŞƏHƏR"])  # işıqlarla
    exact = store.search("işıq", 10, 0, True)
    assert (exact.count, headwords(exact.results)) == (1, ["İŞIQ"])


def test_search_needs_all_the_words_and_shows_where_they_are(store):
    out = store.search("su qabı", 10, 0, False)
    assert (out.count, headwords(out.results)) == (1, ["SU"])
    assert "Su qabı doldu" in out.results[0].snippet
    assert (out.results[0].volume, out.results[0].pdf_page, out.results[0].column) == (4, 9, 2)


def test_the_headword_a_query_spells_comes_first(store):
    assert store.search("su", 10, 0, False).results[0].headword == "SU"
    assert store.search("kitab", 10, 0, False).results[0].headword == "KİTAB"


def test_search_pages_through_its_results(store):
    first = store.search("kitab", 2, 0, False)
    assert (first.count, len(first.results), first.next_offset) == (3, 2, 2)
    second = store.search("kitab", 2, 2, False)
    assert (len(second.results), second.next_offset) == (1, None)
    assert {hit.id for hit in first.results} | {hit.id for hit in second.results} == {15, 16, 17}
    beyond = store.search("kitab", 10, 5, False)
    assert (beyond.count, beyond.results, beyond.next_offset) == (3, [], None)


def test_a_snippet_of_a_long_entry_is_short_and_holds_the_word(store):
    (hit,) = store.search("mənasının", 10, 0, True).results
    assert hit.headword == "OLMAQ"
    assert len(hit.snippet) < 300
    assert "mənasının" in hit.snippet


def test_a_search_reads_a_headword_as_printed(store):
    plain = store.search("çay", 10, 0, False).count
    assert store.search("ÇAY²", 10, 0, False).count == plain >= 2
    assert headwords(store.search("ACGÖZ(LÜ)", 10, 0, False).results)[0] == "ACGÖZ(LÜ)"


def test_a_search_says_when_it_used_only_the_first_twelve_words(store):
    out = store.search("su " + " ".join(["qabı"] * 12), 10, 0, False)
    assert out.notes == ["Only the first 12 words were used."]
    assert headwords(out.results) == ["SU"]


def test_a_search_for_a_capital_i_hints_at_the_dotted_one(store):
    out = store.search("Iki", 10, 0, False)
    assert out.count == 0
    assert "İki is not Iki" in out.notes[0]


def test_a_search_with_no_match_says_so(store):
    out = store.search("zzzz", 10, 0, False)
    assert (out.count, out.results, out.next_offset) == (0, [], None)
    assert "Nothing matched" in out.notes[0]


def test_a_search_of_punctuation_is_a_bad_query(store):
    with pytest.raises(BadQuery, match="at least one word"):
        store.search("?!", 10, 0, False)


# -- browse


def test_browse_lists_the_neighbours_in_print_order(store):
    out = store.browse("kitab", None, 1, 1)
    assert [(n.id, n.headword, n.anchor) for n in out.entries] == [
        (14, "İŞIQ", False),
        (15, "KİTAB", True),
        (16, "KİTABÇA", False),
    ]
    assert (out.previous_id, out.next_id) == (13, 17)
    assert out.entries[1].preview.startswith("is. [ər.] Yazılı")


def test_browse_goes_on_from_the_ids_it_gives(store):
    out = store.browse("kitab", None, 0, 0)
    assert [n.id for n in out.entries] == [15]
    onward = store.browse(None, out.next_id, 0, 2)
    assert [n.id for n in onward.entries] == [16, 17, 18]
    assert out.previous_id == 14
    assert [n.id for n in store.browse(None, out.previous_id, 1, 0).entries] == [13, 14]


def test_browse_stops_at_the_ends_of_the_dictionary(store):
    start = store.browse(None, 1, 3, 2)
    assert ([n.id for n in start.entries], start.previous_id, start.next_id) == ([1, 2, 3], None, 4)
    end = store.browse(None, 21, 2, 5)
    assert ([n.id for n in end.entries], end.previous_id, end.next_id) == ([19, 20, 21], 18, None)


def test_browse_from_the_beginning_of_a_word_starts_at_the_first_headword_with_it(store):
    out = store.browse("kitabx", None, 0, 1)
    assert [(n.id, n.headword, n.anchor) for n in out.entries] == [
        (17, "KİTABXANA", True),
        (18, "OLMAQ", False),
    ]
    assert "starts at the first that begins with it" in out.notes[0]


def test_browse_finds_a_word_spelled_without_accents_and_says_so(store):
    out = store.browse("KITAB", None, 0, 0)
    assert [n.id for n in out.entries] == [15]
    assert "No headword is spelled" in out.notes[0]


def test_the_preview_of_a_long_entry_is_cut(store):
    out = store.browse("olmaq", None, 0, 0)
    assert out.entries[0].preview.endswith("…")
    assert len(out.entries[0].preview) <= store_module.PREVIEW + 1


@pytest.mark.parametrize(("word", "entry_id"), [(None, None), ("su", 3)])
def test_browse_wants_one_of_a_word_and_an_id(store, word, entry_id):
    with pytest.raises(BadQuery, match="one of them"):
        store.browse(word, entry_id, 1, 1)


def test_browse_reports_what_it_cannot_find(store):
    with pytest.raises(NotFound, match="No entry has id 999"):
        store.browse(None, 999, 1, 1)
    with pytest.raises(NotFound, match="No headword matches 'zzz'"):
        store.browse("zzz", None, 1, 1)
    with pytest.raises(BadQuery, match="word to start from"):
        store.browse("!!", None, 1, 1)


# -- the database and the index


def test_without_a_database_every_question_says_how_to_set_one(tmp_path):
    empty = Store(None, tmp_path)
    for ask in (
        lambda: empty.define("su", 500),
        lambda: empty.search("su", 10, 0, False),
        lambda: empty.browse("su", None, 1, 1),
        lambda: empty.read_entry(1, 0, 500),
    ):
        with pytest.raises(NotConfigured, match="IZAHLI_DB"):
            ask()


def test_the_store_reads_its_database_and_cache_from_the_environment(
    monkeypatch, source_db, tmp_path
):
    monkeypatch.setenv("IZAHLI_DB", str(source_db))
    monkeypatch.setenv("IZAHLI_CACHE_DIR", str(tmp_path / "mine"))
    assert headwords(Store.from_env().define("su", 500).entries) == ["SU"]
    assert len(list((tmp_path / "mine").glob("index-*.sqlite"))) == 1
    monkeypatch.delenv("IZAHLI_DB")
    with pytest.raises(NotConfigured):
        Store.from_env().define("su", 500)


def test_a_database_that_appears_later_is_used_on_the_next_question(tmp_path, make_source):
    path = tmp_path / "later.sqlite"
    later = Store(path, tmp_path / "cache")
    with pytest.raises(BadDatabase, match="does not exist"):
        later.define("su", 500)
    make_source(path)
    assert headwords(later.define("su", 500).entries) == ["SU"]


def test_a_cache_deleted_while_the_server_runs_is_built_again(tmp_path, make_source, count_builds):
    cache = tmp_path / "cache"
    running = Store(make_source(tmp_path / "source.sqlite"), cache)
    running.define("su", 500)
    shutil.rmtree(cache)
    assert headwords(running.define("su", 500).entries) == ["SU"]
    assert len(count_builds) == 2


def test_two_servers_with_different_databases_can_share_a_cache_folder(tmp_path, make_source):
    cache = tmp_path / "cache"
    one = Store(make_source(tmp_path / "one.sqlite", [("SU", None, "is. one.", 1, 26, 1)]), cache)
    two = Store(make_source(tmp_path / "two.sqlite", [("SU", None, "is. two.", 1, 26, 1)]), cache)
    assert one.define("su", 500).entries[0].text == "is. one."
    assert two.define("su", 500).entries[0].text == "is. two."
    assert one.define("su", 500).entries[0].text == "is. one."


def test_questions_asked_at_once_build_the_index_once(tmp_path, make_source, count_builds):
    fresh = Store(make_source(tmp_path / "source.sqlite"), tmp_path / "cache")
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda _: fresh.define("su", 500), range(8)))
    assert all(headwords(out.entries) == ["SU"] for out in results)
    assert len(count_builds) == 1
