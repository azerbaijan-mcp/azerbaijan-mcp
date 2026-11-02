import re

import pytest

from azerbaijan_mcp_izahli import text as rules
from azerbaijan_mcp_izahli.text import Pointer

EN_DASH = "\u2013"


@pytest.mark.parametrize(
    ("raw", "folded"),
    [
        ("İŞIQ", "işıq"),
        ("ISIQ", "ısıq"),
        ("Kitab", "kitab"),
        ("ƏLİ", "əli"),
        ("ÖD", "öd"),
        ("Ğ", "ğ"),
        ("i\u0307ki", "iki"),  # an i with a combining dot above is the plain i
        ("MüHIT", "mühıt"),  # a letter and its combining mark become one letter
    ],
)
def test_fold_lower_cases_the_azerbaijani_way(raw, folded):
    assert rules.fold(raw) == folded


@pytest.mark.parametrize(
    ("raw", "plain"),
    [
        ("ŞƏHƏR", "seher"),
        ("Çiçək", "cicek"),
        ("AB-HAVA", "abhava"),
        ("IŞIQ", "isiq"),
        ("Ağ", "ag"),
    ],
)
def test_accent_free_drops_accents_and_hyphens(raw, plain):
    assert rules.accent_free(raw) == plain


@pytest.mark.parametrize(
    ("typed", "forms"),
    [
        ("  Su! ", ["su"]),
        ("ÇAY²", ["çay"]),
        ("çay2", ["çay"]),  # the homonym number as printed in a pointer
        ('"kitab"', ["kitab"]),
        ("\u2018çay\u2019", ["çay"]),
        ("kitab   oxumaq", ["kitab oxumaq"]),
        ("(ata-baba)", ["ata-baba"]),
        ("AB(B)ASI", ["abası", "abbası"]),
        ("ACGÖZ(LÜ)", ["acgöz", "acgözlü"]),
        ("AB-HAVA, ABÜHAVA", ["ab-hava", "abühava"]),
        ("RAD[D]Ə", ["radə", "raddə"]),
        ("ata" + EN_DASH + "baba", ["ata-baba"]),
        ("ata\u2011baba", ["ata-baba"]),
        ("ata\u00adbaba", ["atababa"]),  # a soft hyphen is invisible
        ("ç\u200bay", ["çay"]),  # so is a zero-width space
        ("i\u0307ki", ["iki"]),
        ("...", []),
    ],
)
def test_a_typed_word_is_read_as_the_spellings_it_stands_for(typed, forms):
    assert rules.query_forms(typed) == forms


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("ADLIQ:", "ADLIQ"),
        ("ABNOS,", "ABNOS"),
        ("AB-HAVA,ABÜHAVA", "AB-HAVA, ABÜHAVA"),
        ("  AĞ   ÇA ", "AĞ ÇA"),
    ],
)
def test_clean_headword_drops_what_the_extraction_leaves_behind(raw, clean):
    assert rules.clean_headword(raw) == clean


@pytest.mark.parametrize(
    ("raw", "homonym", "shown"),
    [
        ("ÇAY", 1, "ÇAY¹"),
        ("ÇAY", 2, "ÇAY²"),
        ("A", 10, "A¹⁰"),
        ("SU", None, "SU"),
        ("ADLIQ:", None, "ADLIQ"),
    ],
)
def test_display_headword_marks_homonyms_with_a_superscript(raw, homonym, shown):
    assert rules.display_headword(raw, homonym) == shown


def test_the_homonym_mark_can_be_taken_off_again():
    assert [rules.strip_homonym_mark(w) for w in ("ÇAY²", "A¹⁰", "SU")] == ["ÇAY", "A", "SU"]


@pytest.mark.parametrize(
    ("raw", "forms"),
    [
        ("AB(B)ASI", ["abası", "abbası"]),
        ("ACGÖZ(LÜ)", ["acgöz", "acgözlü"]),
        ("RAD[D]Ə", ["radə", "raddə"]),
        ("AB-HAVA,ABÜHAVA", ["ab-hava", "abühava"]),
        ("ADLIQ:", ["adlıq"]),
        ("BƏİSTİLAH...", ["bəistilah"]),
        ("BAĞIŞLAN(IL)MAZLIQ", ["bağışlanmazlıq", "bağışlanılmazlıq"]),
        ("Xİ-Xİ-Xİ!", ["xi-xi-xi"]),
        ("AH-FƏRYAD,", ["ah-fəryad"]),
        ("SU,SU", ["su"]),
        (",", []),
    ],
)
def test_headword_forms_lists_every_spelling(raw, forms):
    assert rules.headword_forms(raw) == forms


def test_two_optional_groups_give_four_spellings_and_many_give_two():
    assert sorted(rules.headword_forms("A(B)C(D)")) == ["abc", "abcd", "ac", "acd"]
    assert rules.headword_forms("A(1)B(2)C(3)D(4)E(5)") == ["abcde", "a1b2c3d4e5"]


def test_the_vocabulary_counts_words_with_their_hyphens_and_leaves_cut_words_out():
    vocabulary = rules.build_vocabulary(
        ["Nəsil ata-baba haqqında. Ata-baba yurdu.", "gecə-\ndir yoxdur"], ["ata-baba"]
    )
    assert vocabulary["ata-baba"] == 3
    assert vocabulary["yurdu"] == 1
    assert "gecədir" not in vocabulary
    assert "gecə-dir" not in vocabulary


def test_the_vocabulary_reads_every_kind_of_line_break():
    vocabulary = rules.build_vocabulary(["kitab-\r\nxana", "su-\fyu", "ata-\u2028baba"], [])
    assert not any("-" in word for word in vocabulary)
    assert {"kitab", "xana", "su", "yu", "ata", "baba"} <= set(vocabulary)


VOCABULARY = {
    "ata-baba": 3,
    "kitabxana": 2,
    "sinə-sinə": 5,
    "sinəsinə": 1,
    "bəd-bəxt": 1,
    "bədbəxt": 5,
    "bulbul": 1,
}


@pytest.mark.parametrize(
    ("raw", "joined"),
    [
        ("Kitab-\nxana açıldı.", "Kitabxana açıldı."),  # a word the line cut
        ("Kitab-\r\nxana açıldı.", "Kitabxana açıldı."),  # whatever breaks the line
        ("Kitab-\fxana açıldı.", "Kitabxana açıldı."),
        ("Kitab-\u2028xana açıldı.", "Kitabxana açıldı."),
        ("Ata-\nbaba yurdu.", "Ata-baba yurdu."),  # a compound that broke at its hyphen
        ("gecə-\ndir", "gecədir"),  # unknown: the line cut it, as it usually does
        ("Sinə-\nsinə", "Sinə-sinə"),  # both spellings occur, the hyphen is the common one
        ("bəd-\nbəxt", "bədbəxt"),  # both occur, the plain one is the common one
        ("aşkar-\naşkar", "aşkar-aşkar"),  # a doubled word is never one word
        ("Öskürə-\nöskürə", "Öskürə-öskürə"),
        ("bul-\nbul", "bulbul"),  # unless the dictionary has the one word
        ("ba-\nba", "baba"),  # a doubled syllable is a word cut in two
        ("1931-\nci ildə", "1931-ci ildə"),  # a number with its ending
        ("baxarpa2-\nci", "baxarpa2-ci"),
        ("qeyri-\netimad", "qeyri-etimad"),  # the prefix qeyri- always has its hyphen
        ("qeyri-\nsi", "qeyrisi"),
        ("Abi-\nHəyat", "Abi-Həyat"),  # a capital after the hyphen is no word cut by the line
        ("Su qabı,\nçay\n  içki", "Su qabı, çay içki"),
        ("b a x ağça.", "bax ağça."),
        ("B a x ağça.", "Bax ağça."),
        ("b a xyz", "b a xyz"),
        ("Mühit", "Mühit"),  # a letter and its combining mark become one character
    ],
)
def test_dewrap_joins_lines_and_keeps_the_hyphens_that_belong(raw, joined):
    assert rules.dewrap(raw, VOCABULARY) == joined


def test_dewrap_is_idempotent():
    once = rules.dewrap("Ata-\nbaba yurdu.\nB a x ağça.", VOCABULARY)
    assert rules.dewrap(once, VOCABULARY) == once


@pytest.mark.parametrize(
    ("text", "origin"),
    [
        ("[fars.] is. klas. Su.", "fars."),
        ("is. [ər.] Yazılı cild.", "ər."),
        ("sif. [əsli lat.] Böyük.", "əsli lat."),
        ("sif. və zərf [fars.] Asta, yavaş.", "fars."),
        ("is. və sif. [ər.] Yaxşı.", "ər."),
        ("zərf və sif. [ər. amir və fars. ...anə] Əmrlə.", "ər. amir və fars. ...anə"),
        ("ABNUS is. [fars.] Su.", "fars."),  # the variant headword that opens some entries
        ("is. [Vaqif:] Nə gözəl gündür.", None),  # a speaker, not an origin
        ("sif. Çağıran. [Qadının] amiranə dedi.", None),  # a name in the first example
        ("is. bax baxış [Mirzə] dedi.", None),  # a pointer is not a label
        ("bax ağça.", None),
        ("is. Su qabı.", None),
    ],
)
def test_origin_is_the_bracket_that_opens_the_entry(text, origin):
    assert rules.origin_of(text) == origin


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("bax abi-həyat.", [Pointer("abi-həyat", ("abi-həyat",))]),
        ("bax dərd 3-cü mənada. Kənarda", [Pointer("dərd 3-cü mənada", ("dərd",))]),
        ("bax baxış 1 və 2-ci mənalarda.", [Pointer("baxış 1 və 2-ci mənalarda", ("baxış",))]),
        ("bax acımaq1 3-cü mənada.", [Pointer("acımaq1 3-cü mənada", ("acımaq",), 1)]),
        ("bax acınacaq(lı).", [Pointer("acınacaq(lı)", ("acınacaq", "acınacaqlı"))]),
        ("(bax çətirli 2-ci mənada).", [Pointer("çətirli 2-ci mənada", ("çətirli",))]),
        (
            "bax ayaq üstə qalmaq; 2) axıra",
            [Pointer("ayaq üstə qalmaq", ("ayaq üstə qalmaq", "ayaq"))],
        ),
        ("zərf bax ağça.", [Pointer("ağça", ("ağça",))]),
        ("f. 1. bax acmaq. 2. məh. Yoxsullaşmaq.", [Pointer("acmaq", ("acmaq",))]),
        ("[fr.] bax təyyarə. Qəzəl", [Pointer("təyyarə", ("təyyarə",))]),
        ("Abi-bəqa " + EN_DASH + " bax abi-həyat.", [Pointer("abi-həyat", ("abi-həyat",))]),
    ],
)
def test_pointers_read_what_bax_sends_the_reader_to(text, expected):
    assert rules.pointers(text) == expected


def test_several_headwords_after_one_bax_are_several_pointers():
    found = rules.pointers("bax belə-belə, cıb-cıbılı, ətcəbala. S.Rəhimov.")
    assert [pointer.text for pointer in found] == ["belə-belə", "cıb-cıbılı", "ətcəbala"]


def test_a_pointer_in_a_phrase_entry_is_found_and_a_repeat_is_not_counted_twice():
    found = rules.pointers(
        f"Abi-bəqa {EN_DASH} bax abi-həyat. Abi-heyvan(i) {EN_DASH} bax abihəyat. "
        f"{EN_DASH} bax abi-həyat."
    )
    assert [pointer.text for pointer in found] == ["abi-həyat", "abihəyat"]


def test_a_long_pointer_is_cut_between_words_not_inside_one():
    (pointer,) = rules.pointers("bax " + " ".join(["söz"] * 40) + ".")
    assert len(pointer.text) <= rules.MAX_POINTER
    assert set(pointer.text.split()) == {"söz"}


@pytest.mark.parametrize(
    "text",
    [
        "Bax, şit yağı da basıblar.",
        "Sən gəl, bax, gör.",
        "O baxmaq istədi.",
        "məbax evi",
        "bax Aleksandr.",
        "Bax bu qaşa, bax bu gözə.",  # the verb in a quotation
        "O dedi ki, sən də bax bu gözə.",
    ],
)
def test_the_word_bax_in_running_text_is_not_a_pointer(text):
    assert rules.pointers(text) == []


@pytest.mark.parametrize(
    ("text", "redirect"),
    [
        ("bax ağça.", True),
        ("is. bax baxış 1-ci mənada.", True),
        ("f. 1. bax acmaq. 2. məh. Yoxsullaşmaq.", True),
        ("[fr.] bax təyyarə. Qəzəl olmasaydı", True),
        ("is. [fr.] bax təyyarə.", True),
        ("is. Su qabı. Bax, gör.", False),
        ("is. Kiçik kitab, bukləd. □ Cib kitabçası " + EN_DASH + " bax kitab.", False),
        ("sif. Doymaq bilməyən.", False),
    ],
)
def test_an_entry_that_only_points_elsewhere_is_a_redirect(text, redirect):
    assert rules.is_redirect(text) is redirect


def test_window_cuts_at_spaces_and_the_pieces_make_the_text_again():
    text = " ".join(f"söz{n}" for n in range(1, 60))
    pieces, offset = [], 0
    while offset is not None:
        piece, offset = rules.window(text, offset, 50)
        pieces.append(piece)
    assert len(pieces) > 3
    assert all(0 < len(piece) <= 50 for piece in pieces)
    assert " ".join(pieces) == text


def test_window_edges():
    assert rules.window("abc", 0, 200) == ("abc", None)
    assert rules.window("abc", 3, 200) == ("", None)
    assert rules.window("abc", 99, 200) == ("", None)
    assert rules.window("a" * 100, 0, 30) == ("a" * 30, 30)  # no space to cut at


LONG = "Başlanğıc cümlə. " * 20 + "Burada İşıq sözü var. " + "Sonluq cümlə. " * 20


def test_snippet_centres_on_the_first_hit_and_maps_back_through_the_capital_i():
    out = rules.snippet(LONG, ["işıq"], width=80)
    assert "İşıq" in out
    assert out.startswith("…")
    assert out.endswith("…")
    assert len(out) < 120


def test_snippet_centres_on_the_word_not_on_the_letters_inside_another_word():
    text = "Belini bağladı. " * 15 + "Burada el sözü var. " + "Sonluq cümlə. " * 15
    _, patterns = rules.match_terms(["el"], False)
    assert " el " in rules.snippet(text, patterns, width=80)


def test_snippet_without_a_hit_starts_at_the_beginning_and_short_text_is_whole():
    assert rules.snippet(LONG, ["yoxdur"], width=80).startswith("Başlanğıc")
    assert rules.snippet("Qısa mətn.", ["mətn"]) == "Qısa mətn."


@pytest.mark.parametrize(
    ("query", "words"),
    [
        ("Su, QABI! İşıq", ["su", "qabı", "işıq"]),
        ("ÇAY²", ["çay"]),
        ("ACGÖZ(LÜ)", ["acgöz"]),
        ("RAD[D]Ə", ["radə"]),
        ("su (maye)", ["su", "maye"]),
        ("...", []),
    ],
)
def test_query_words_are_folded_and_a_printed_headword_is_read_as_its_stem(query, words):
    assert rules.query_words(query) == words


def test_query_words_keep_every_word_for_the_store_to_count():
    assert len(rules.query_words(" ".join(["söz"] * 30))) == 30


@pytest.mark.parametrize(
    ("words", "exact", "expression"),
    [
        (["su", "qabı"], False, '"su" AND "qabı"*'),
        (["içməkdən"], False, '"içmək"*'),
        (["kitab"], False, '"kitab"*'),
        (["kitabxana", "su"], True, '"kitabxana" AND "su"'),
        ([], False, ""),
    ],
)
def test_match_terms_cut_long_words_to_five_letters_unless_exact(words, exact, expression):
    found, patterns = rules.match_terms(words, exact)
    assert found == expression
    assert len(patterns) == len(words)


def test_the_patterns_find_the_words_where_they_begin():
    _, (short, long) = rules.match_terms(["su", "qabı"], False)
    assert re.search(short, "su içmək")
    assert not re.search(short, "susuz")
    assert not re.search(short, "kasu")
    assert re.search(long, "qabıq var")  # a long word is matched as a prefix
    assert not re.search(long, "ağqabı")
    _, (whole,) = rules.match_terms(["qabı"], True)
    assert re.search(whole, "bir qabı al")
    assert not re.search(whole, "qabıq")


@pytest.mark.parametrize(
    ("a", "b", "limit", "distance"),
    [
        ("kitab", "kitab", 2, 0),
        ("kitab", "kitba", 1, 1),  # two neighbours swapped
        ("kitab", "kitap", 1, 1),
        ("kitab", "kitaba", 1, 1),
        ("kitab", "kita", 1, 1),
        ("kitab", "kitxyz", 2, None),
        ("abc", "xyz", 2, None),
        ("a", "abcdef", 2, None),  # too different in length to be close
    ],
)
def test_edit_distance_counts_edits_up_to_a_limit(a, b, limit, distance):
    assert rules.edit_distance(a, b, limit) == distance
