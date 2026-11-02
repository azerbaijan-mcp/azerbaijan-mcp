# ruff: noqa: RUF001
from decimal import Decimal

import pytest

from azerbaijan_mcp_utils import words


def az(amount, **kwargs):
    return words.amount_in_words(amount, "az", **kwargs).text


def en(amount):
    return words.amount_in_words(amount, "en").text


def ru(amount):
    return words.amount_in_words(amount, "ru").text


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (0, "sıfır manat"),
        (1, "bir manat"),
        (10, "on manat"),
        (11, "on bir manat"),
        (21, "iyirmi bir manat"),
        (90, "doxsan manat"),
        (100, "yüz manat"),
        (101, "yüz bir manat"),
        (110, "yüz on manat"),
        (200, "iki yüz manat"),
        (999, "doqquz yüz doxsan doqquz manat"),
        (1000, "min manat"),
        (1001, "min bir manat"),
        (1100, "min yüz manat"),
        (2000, "iki min manat"),
        (12345, "on iki min üç yüz qırx beş manat"),
        (100000, "yüz min manat"),
        (101000, "yüz bir min manat"),
        (1000000, "bir milyon manat"),
        (1000001, "bir milyon bir manat"),
        (1001000, "bir milyon min manat"),
        (2500000, "iki milyon beş yüz min manat"),
        (1000000000, "bir milyard manat"),
        ("1234.56", "min iki yüz otuz dörd manat əlli altı qəpik"),
        ("0.05", "sıfır manat beş qəpik"),
        ("12.50", "on iki manat əlli qəpik"),
        ("5.00", "beş manat"),
    ],
)
def test_azerbaijani_amounts(amount, text):
    assert az(amount) == text


def test_azerbaijani_with_bir_min_writes_bir_before_a_single_thousand_only():
    assert az(1000, bir_min=True) == "bir min manat"
    assert az("1547.32", bir_min=True) == "bir min beş yüz qırx yeddi manat otuz iki qəpik"
    assert az(2000, bir_min=True) == "iki min manat"
    assert az(1001000, bir_min=True) == "bir milyon bir min manat"
    assert az(100, bir_min=True) == "yüz manat"


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (0, "zero manat"),
        (13, "thirteen manat"),
        (20, "twenty manat"),
        (21, "twenty-one manat"),
        (99, "ninety-nine manat"),
        (100, "one hundred manat"),
        (101, "one hundred one manat"),
        (1000, "one thousand manat"),
        (1001, "one thousand one manat"),
        (12345, "twelve thousand three hundred forty-five manat"),
        (1000000, "one million manat"),
        (1000000000, "one billion manat"),
        ("1234.56", "one thousand two hundred thirty-four manat and fifty-six qəpik"),
        ("0.05", "zero manat and five qəpik"),
        ("1.00", "one manat"),
    ],
)
def test_english_amounts(amount, text):
    assert en(amount) == text


@pytest.mark.parametrize(
    ("amount", "text"),
    [
        (0, "ноль манатов"),
        (1, "один манат"),
        (2, "два маната"),
        (4, "четыре маната"),
        (5, "пять манатов"),
        (11, "одиннадцать манатов"),
        (12, "двенадцать манатов"),
        (21, "двадцать один манат"),
        (22, "двадцать два маната"),
        (100, "сто манатов"),
        (1000, "одна тысяча манатов"),
        (2000, "две тысячи манатов"),
        (5000, "пять тысяч манатов"),
        (11000, "одиннадцать тысяч манатов"),
        (21000, "двадцать одна тысяча манатов"),
        (22000, "двадцать две тысячи манатов"),
        (1000000, "один миллион манатов"),
        (2000000, "два миллиона манатов"),
        (1000001, "один миллион один манат"),
        (1000000000, "один миллиард манатов"),
        ("1234.56", "одна тысяча двести тридцать четыре маната пятьдесят шесть гяпиков"),
        ("0.01", "ноль манатов один гяпик"),
        ("0.02", "ноль манатов два гяпика"),
        ("0.21", "ноль манатов двадцать один гяпик"),
    ],
)
def test_russian_amounts(amount, text):
    assert ru(amount) == text


def test_the_largest_amount_is_written_in_all_three_languages():
    largest = "999999999999.99"
    assert az(largest).startswith("doqquz yüz doxsan doqquz milyard")
    assert az(largest).endswith("doxsan doqquz manat doxsan doqquz qəpik")
    assert en(largest).startswith("nine hundred ninety-nine billion")
    assert ru(largest).startswith("девятьсот девяносто девять миллиардов")
    assert ru(largest).endswith("манатов девяносто девять гяпиков")


@pytest.mark.parametrize(
    "written",
    [
        "1234.56",
        "1 234,56",
        "1234,56",
        " 1234.56 ",
        "1'234.56",
        "1 234.56",
        1234.56,
        Decimal("1234.56"),
    ],
)
def test_the_ways_of_writing_an_amount_that_are_understood(written):
    assert words.parse_amount(written) == (1234, 56)


def test_whole_numbers_and_short_decimals():
    assert words.parse_amount(1234) == (1234, 0)
    assert words.parse_amount("1234.5") == (1234, 50)
    assert words.parse_amount("0") == (0, 0)
    assert words.parse_amount("12.00") == (12, 0)
    assert words.parse_amount("999999999999.99") == (999999999999, 99)


@pytest.mark.parametrize(
    ("written", "message"),
    [
        ("-1", "must not be negative"),
        (-5, "must not be negative"),
        ("1.234", "at most two decimals"),
        ("0.001", "at most two decimals"),
        ("1,234.5", "two kinds of decimal separator"),
        ("1.234,5", "two kinds of decimal separator"),
        ("abc", "is not an amount"),
        ("", "is not an amount"),
        ("1e3", "is not an amount"),
        (".5", "is not an amount"),
        ("12.", "is not an amount"),
        (True, "is not an amount"),
        (1e16, "is not an amount"),
        ("1000000000000", "below one trillion"),
        (10**12, "below one trillion"),
    ],
)
def test_amounts_that_cannot_be_written_in_words(written, message):
    with pytest.raises(words.AmountError, match=message):
        words.parse_amount(written)


def test_float_noise_is_refused_not_rounded():
    with pytest.raises(words.AmountError, match="at most two decimals"):
        words.parse_amount(0.1 + 0.2)


def test_an_unknown_language_is_refused():
    with pytest.raises(words.AmountError, match="lang must be one of az, en, ru"):
        words.amount_in_words(5, "de")


def test_the_amount_keeps_its_parts_and_a_two_decimal_text():
    amount = words.amount_in_words("1234.5", "en")
    assert (amount.manat, amount.qepik, amount.decimal) == (1234, 50, "1234.50")
    assert words.amount_in_words(0.05, "az").decimal == "0.05"
