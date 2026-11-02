# ruff: noqa: RUF001, RUF002
"""Azerbaijani Latin and Cyrillic transliteration.

Source: the 32 letters of the modern Azerbaijani Latin alphabet and the 32 letters of the Cyrillic
alphabet used from 1958 to 1991 correspond one to one
(https://en.wikipedia.org/wiki/Azerbaijani_alphabet, and the table in "Essentials of Azerbaijani",
https://minio.la.utexas.edu/webeditor-files/slavic/pdf/azeri.pdf). Letters are mapped one by one
and case is kept letter by letter, because Python's own case rules are wrong for the Azerbaijani
dotted and dotless i. The Cyrillic letters the 1958 alphabet dropped (Я, Ю, Ё, Щ, Ц, Ь, Ъ, Э, Й)
and any other letter outside the table are left as they are and reported.
"""

from typing import Literal

Direction = Literal["latin_to_cyrillic", "cyrillic_to_latin"]
DIRECTIONS = ("latin_to_cyrillic", "cyrillic_to_latin")

# Latin upper, Latin lower, Cyrillic upper, Cyrillic lower
LETTERS = (
    ("A", "a", "А", "а"),
    ("B", "b", "Б", "б"),
    ("C", "c", "Ҹ", "ҹ"),
    ("Ç", "ç", "Ч", "ч"),
    ("D", "d", "Д", "д"),
    ("E", "e", "Е", "е"),
    ("Ə", "ə", "Ә", "ә"),
    ("F", "f", "Ф", "ф"),
    ("G", "g", "Ҝ", "ҝ"),
    ("Ğ", "ğ", "Ғ", "ғ"),
    ("H", "h", "Һ", "һ"),
    ("X", "x", "Х", "х"),
    ("I", "ı", "Ы", "ы"),
    ("İ", "i", "И", "и"),
    ("J", "j", "Ж", "ж"),
    ("K", "k", "К", "к"),
    ("Q", "q", "Г", "г"),
    ("L", "l", "Л", "л"),
    ("M", "m", "М", "м"),
    ("N", "n", "Н", "н"),
    ("O", "o", "О", "о"),
    ("Ö", "ö", "Ө", "ө"),
    ("P", "p", "П", "п"),
    ("R", "r", "Р", "р"),
    ("S", "s", "С", "с"),
    ("Ş", "ş", "Ш", "ш"),
    ("T", "t", "Т", "т"),
    ("U", "u", "У", "у"),
    ("Ü", "ü", "Ү", "ү"),
    ("V", "v", "В", "в"),
    ("Y", "y", "Ј", "ј"),
    ("Z", "z", "З", "з"),
)
LATIN_TO_CYRILLIC = {
    latin: cyrillic
    for upper, lower, cyrillic_upper, cyrillic_lower in LETTERS
    for latin, cyrillic in ((upper, cyrillic_upper), (lower, cyrillic_lower))
}
CYRILLIC_TO_LATIN = {cyrillic: latin for latin, cyrillic in LATIN_TO_CYRILLIC.items()}


def transliterate(text: str, direction: Direction) -> tuple[str, str]:
    """The converted text and the letters that were left as they were."""
    table = LATIN_TO_CYRILLIC if direction == "latin_to_cyrillic" else CYRILLIC_TO_LATIN
    converted = []
    unchanged: dict[str, None] = {}
    for char in text:
        if char in table:
            converted.append(table[char])
            continue
        converted.append(char)
        if char.isalpha():
            unchanged[char] = None
    return "".join(converted), "".join(unchanged)
