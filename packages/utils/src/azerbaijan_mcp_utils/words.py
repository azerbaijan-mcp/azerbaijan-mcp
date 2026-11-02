"""Amounts in manat written in words: Azerbaijani, English and Russian.

Sources and conventions:
- Azerbaijani: the numerals (bir, iki, ...; on, iyirmi, ...; yüz, min, milyon, milyard) and the
  rule that yüz and min stand without "bir" in running text, as in the school textbooks at
  http://e-derslik.edu.az (for example "min doqquz yüz otuz iki"). Many financial documents write
  "bir min"; `bir_min` gives that style, as in https://birhesab.az/az/hesablayici/azn-sozle/
  ("Bir min beş yüz qırx yeddi manat otuz iki qəpik").
- Russian: gender and plural forms of the standard numerals (одна тысяча, две тысячи, пять тысяч;
  один миллион). The names are манат and гяпик (https://ru.wikipedia.org/wiki/Гяпик).
- English: the short scale (thousand, million, billion). The subunit is written qəpik, its
  Azerbaijani spelling, because English spellings differ (gapik, gepik, qapik).
The amount is exact: at most two decimals, never rounded, and below one trillion.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

MAX_AMOUNT = 10**12
LANGS = ("az", "en", "ru")

AZ_ONES = ("", "bir", "iki", "üç", "dörd", "beş", "altı", "yeddi", "səkkiz", "doqquz")
AZ_TENS = ("", "on", "iyirmi", "otuz", "qırx", "əlli", "altmış", "yetmiş", "səksən", "doxsan")
AZ_SCALES = ("", "min", "milyon", "milyard")

EN_ONES = (
    *("", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"),
    *("eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen"),
    *("eighteen", "nineteen"),
)
EN_TENS = ("", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
EN_SCALES = ("", "thousand", "million", "billion")

RU_ONES = ("", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять")
RU_ONES_FEMININE = ("", "одна", "две", *RU_ONES[3:])
RU_TEENS = (
    *("десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать"),
    *("пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"),
)
RU_TENS = (
    *("", "", "двадцать", "тридцать", "сорок", "пятьдесят"),
    *("шестьдесят", "семьдесят", "восемьдесят", "девяносто"),
)
RU_HUNDREDS = (
    *("", "сто", "двести", "триста", "четыреста", "пятьсот"),
    *("шестьсот", "семьсот", "восемьсот", "девятьсот"),
)
RU_SCALES = (
    None,
    (("тысяча", "тысячи", "тысяч"), True),
    (("миллион", "миллиона", "миллионов"), False),
    (("миллиард", "миллиарда", "миллиардов"), False),
)
RU_MANAT = ("манат", "маната", "манатов")
RU_QEPIK = ("гяпик", "гяпика", "гяпиков")


class AmountError(ValueError):
    """The amount cannot be written in words."""


@dataclass(frozen=True, slots=True)
class Amount:
    manat: int
    qepik: int
    text: str

    @property
    def decimal(self) -> str:
        return f"{self.manat}.{self.qepik:02d}"


def parse_amount(value: str | int | float | Decimal) -> tuple[int, int]:
    """Split an amount into whole manat and qəpik. Spaces and a decimal comma are accepted."""
    if isinstance(value, bool):
        raise AmountError(f"{value!r} is not an amount.")
    text = format(value, "f") if isinstance(value, Decimal) else str(value)
    text = re.sub(r"[\s']", "", text)
    if "," in text and "." in text:
        raise AmountError(f"{value!r} has two kinds of decimal separator; use one.")
    text = text.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        raise AmountError(f"{value!r} is not an amount such as 1234.56.")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:  # pragma: no cover - the pattern above rules this out
        raise AmountError(f"{value!r} is not an amount such as 1234.56.") from exc
    if amount < 0:
        raise AmountError("The amount must not be negative.")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise AmountError("An amount has at most two decimals (qəpik); nothing is rounded.")
    if amount >= MAX_AMOUNT:
        raise AmountError("The amount must be below one trillion (10^12).")
    return divmod(int(cents), 100)


def _groups(number: int) -> list[int]:
    """The three-digit groups of a number, lowest first."""
    groups = []
    while number:
        number, group = divmod(number, 1000)
        groups.append(group)
    return groups


def az_words(number: int, bir_min: bool = False) -> str:
    if number == 0:
        return "sıfır"
    parts: list[str] = []
    for scale, group in reversed(list(enumerate(_groups(number)))):
        if group == 0:
            continue
        hundreds, rest = divmod(group, 100)
        words = ([AZ_ONES[hundreds]] if hundreds > 1 else []) + (["yüz"] if hundreds else [])
        words += [AZ_TENS[rest // 10], AZ_ONES[rest % 10]]
        words = [word for word in words if word]
        if scale == 1 and group == 1:
            words = ["bir", "min"] if bir_min else ["min"]
        elif scale:
            words.append(AZ_SCALES[scale])
        parts += words
    return " ".join(parts)


def en_words(number: int) -> str:
    if number == 0:
        return "zero"
    parts: list[str] = []
    for scale, group in reversed(list(enumerate(_groups(number)))):
        if group == 0:
            continue
        hundreds, rest = divmod(group, 100)
        words = [f"{EN_ONES[hundreds]} hundred"] if hundreds else []
        if rest >= 20:
            tens = EN_TENS[rest // 10]
            words.append(f"{tens}-{EN_ONES[rest % 10]}" if rest % 10 else tens)
        elif rest:
            words.append(EN_ONES[rest])
        if scale:
            words.append(EN_SCALES[scale])
        parts += words
    return " ".join(parts)


def _ru_plural(number: int, forms: tuple[str, str, str]) -> str:
    if 11 <= number % 100 <= 14:
        return forms[2]
    if number % 10 == 1:
        return forms[0]
    return forms[1] if 2 <= number % 10 <= 4 else forms[2]


def ru_words(number: int) -> str:
    """Russian words for the number, masculine at the end, as the nouns manat and gyapik need."""
    if number == 0:
        return "ноль"
    parts: list[str] = []
    for scale, group in reversed(list(enumerate(_groups(number)))):
        if group == 0:
            continue
        feminine = bool(scale) and RU_SCALES[scale][1]
        ones = RU_ONES_FEMININE if feminine else RU_ONES
        hundreds, rest = divmod(group, 100)
        words = [RU_HUNDREDS[hundreds]]
        if 10 <= rest <= 19:
            words.append(RU_TEENS[rest - 10])
        else:
            words += [RU_TENS[rest // 10], ones[rest % 10]]
        if scale:
            words.append(_ru_plural(group, RU_SCALES[scale][0]))
        parts += [word for word in words if word]
    return " ".join(parts)


def amount_in_words(
    value: str | int | float | Decimal, lang: str = "az", bir_min: bool = False
) -> Amount:
    if lang not in LANGS:
        raise AmountError(f"lang must be one of {', '.join(LANGS)}.")
    manat, qepik = parse_amount(value)
    if lang == "az":
        text = f"{az_words(manat, bir_min)} manat"
        if qepik:
            text += f" {az_words(qepik, bir_min)} qəpik"
    elif lang == "en":
        text = f"{en_words(manat)} manat"
        if qepik:
            text += f" and {en_words(qepik)} qəpik"
    else:
        text = f"{ru_words(manat)} {_ru_plural(manat, RU_MANAT)}"
        if qepik:
            text += f" {ru_words(qepik)} {_ru_plural(qepik, RU_QEPIK)}"
    return Amount(manat, qepik, text)
