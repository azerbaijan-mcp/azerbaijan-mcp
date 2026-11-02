import pytest

from azerbaijan_mcp_utils import phone

NOT_994 = "This is not an Azerbaijani number: it must start with +994."
BAD_TEXT = "A phone number has digits and at most + ( ) . - and spaces."


def wrong_length(count: int) -> str:
    return f"An Azerbaijani number has 9 digits after +994 or the leading 0; this one has {count}."


@pytest.mark.parametrize(
    "written",
    [
        "+994 50 123 45 67",
        "+994501234567",
        "+994 (50) 123-45-67",
        "00994 50 123 45 67",
        "994501234567",
        "050 123 45 67",
        "050-123-45-67",
        "(050) 123 45 67",
        "0501234567",
        "501234567",
        "  +994.50.123.45.67  ",
    ],
)
def test_every_way_of_writing_a_mobile_number_gives_the_same_forms(written):
    result = phone.check(written)
    assert result.valid_format
    assert result.e164 == "+994501234567"
    assert result.international == "+994 50 123 45 67"
    assert result.national == "050 123 45 67"
    assert (result.kind, result.area) == ("mobile", None)
    assert (result.problems, result.notes) == ((), ())


@pytest.mark.parametrize("prefix", ["10", "50", "51", "55", "60", "70", "77", "99"])
def test_all_the_listed_mobile_prefixes_are_mobile(prefix):
    assert phone.check(f"0{prefix} 765 43 21").kind == "mobile"


@pytest.mark.parametrize(
    ("prefix", "area"),
    [
        ("12", "Baku"),
        ("18", "Sumqayit"),
        ("22", "Ganja region"),
        ("25", "Lankaran region"),
        ("36", "Nakhchivan Autonomous Republic"),
    ],
)
def test_area_codes_give_a_landline_and_its_area(prefix, area):
    result = phone.check(f"+994 {prefix} 345 67 89")
    assert (result.kind, result.area) == ("landline", area)
    assert result.national == f"0{prefix} 345 67 89"


def test_every_listed_area_code_is_a_landline():
    assert set(phone.AREAS) == {"12", "18", "20", "21", "22", "23", "24", "25", "26", "36"}
    assert not set(phone.AREAS) & phone.MOBILE_PREFIXES


def test_an_unknown_prefix_is_flagged_but_not_rejected():
    result = phone.check("+994 40 123 45 67")
    assert result.valid_format
    assert result.kind == "unknown"
    assert result.international == "+994 40 123 45 67"
    assert result.notes == (
        "The prefix 40 is not in the numbering plan this server knows. "
        "The number may be new or wrong.",
    )


@pytest.mark.parametrize(
    ("written", "problem"),
    [
        ("+90 532 123 45 67", NOT_994),
        ("0090 532 123 45 67", NOT_994),
        ("050 123 45 6", wrong_length(8)),
        ("+994 50 123 45 678", wrong_length(10)),
        ("12345", wrong_length(5)),
        ("call me", BAD_TEXT),
        ("", BAD_TEXT),
        ("+994 50 123 45 6x", BAD_TEXT),
    ],
)
def test_numbers_that_are_not_azerbaijani_or_the_wrong_length_are_rejected(written, problem):
    result = phone.check(written)
    assert not result.valid_format
    assert result.problems == (problem,)
    assert (result.e164, result.international, result.national, result.kind) == (None,) * 4
