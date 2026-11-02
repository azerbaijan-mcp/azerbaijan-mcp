import unicodedata

import pytest

from azerbaijan_mcp_utils import translit


def to_cyrillic(text):
    return translit.transliterate(text, "latin_to_cyrillic")


def to_latin(text):
    return translit.transliterate(text, "cyrillic_to_latin")


def test_each_alphabet_has_32_letters_that_pair_up_one_to_one():
    assert len(translit.LETTERS) == 32
    assert len(translit.LATIN_TO_CYRILLIC) == len(translit.CYRILLIC_TO_LATIN) == 64
    for latin, cyrillic in translit.LATIN_TO_CYRILLIC.items():
        assert len(latin) == len(cyrillic) == 1
        assert translit.CYRILLIC_TO_LATIN[cyrillic] == latin
        assert "LATIN" in unicodedata.name(latin)
        assert "CYRILLIC" in unicodedata.name(cyrillic)


def test_every_letter_survives_a_round_trip_with_its_case():
    for upper, lower, cyrillic_upper, cyrillic_lower in translit.LETTERS:
        for latin, cyrillic in ((upper, cyrillic_upper), (lower, cyrillic_lower)):
            assert to_cyrillic(latin) == (cyrillic, "")
            assert to_latin(cyrillic) == (latin, "")


def test_the_letters_that_differ_most_between_the_alphabets():
    expected = {
        "Ə": "CYRILLIC CAPITAL LETTER SCHWA",
        "C": "CYRILLIC CAPITAL LETTER CHE WITH VERTICAL STROKE",
        "G": "CYRILLIC CAPITAL LETTER KA WITH VERTICAL STROKE",
        "Ğ": "CYRILLIC CAPITAL LETTER GHE WITH STROKE",
        "H": "CYRILLIC CAPITAL LETTER SHHA",
        "Ö": "CYRILLIC CAPITAL LETTER BARRED O",
        "Ü": "CYRILLIC CAPITAL LETTER STRAIGHT U",
        "Y": "CYRILLIC CAPITAL LETTER JE",
        "I": "CYRILLIC CAPITAL LETTER YERU",
        "İ": "CYRILLIC CAPITAL LETTER I",
        "Q": "CYRILLIC CAPITAL LETTER GHE",
        "J": "CYRILLIC CAPITAL LETTER ZHE",
    }
    for latin, name in expected.items():
        assert unicodedata.name(translit.LATIN_TO_CYRILLIC[latin]) == name


@pytest.mark.parametrize(
    ("latin", "cyrillic"),
    [
        ("Azərbaycan", "Азәрбајҹан"),
        ("Bakı", "Бакы"),
        ("Gəncə", "Ҝәнҹә"),
        ("İstiqlal", "Истиглал"),
        ("ŞİRKƏT", "ШИРКӘТ"),
        ("Qarabağ", "Гарабағ"),
        ("Yeni il", "Јени ил"),
        ("ıİiI", "ыИиЫ"),
    ],
)
def test_words_go_both_ways(latin, cyrillic):
    assert to_cyrillic(latin) == (cyrillic, "")
    assert to_latin(cyrillic) == (latin, "")


def test_digits_punctuation_and_spaces_stay():
    assert to_cyrillic("№ 5, 12.03.2026 — Bakı!") == ("№ 5, 12.03.2026 — Бакы!", "")
    assert to_cyrillic("") == ("", "")
    assert to_latin("") == ("", "")


def test_letters_outside_the_tables_are_left_and_reported_once():
    assert to_cyrillic("Wi-Fi WWW") == ("Wи-Фи WWW", "W")
    assert to_latin("Яндекс щит") == ("Яndeks щit", "Ящ")
    assert to_latin("Привет") == ("Privet", "")


def test_text_in_the_other_script_is_left_alone_and_reported():
    result, unchanged = to_cyrillic("Привет")
    assert result == "Привет"
    assert unchanged == "Привет"
