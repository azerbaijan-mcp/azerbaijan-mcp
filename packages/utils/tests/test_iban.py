import socket

import pytest

from azerbaijan_mcp_utils import iban

# The SWIFT IBAN Registry's example for Azerbaijan.
REGISTRY_EXAMPLE = "AZ21NABZ00000000137010001944"
ONLY_ALNUM = "An IBAN has only letters and digits; spaces and hyphens are ignored."


def reference_mod97(text: str) -> int:
    """The check written out as long division, a second way to the same number."""
    moved = text[4:] + text[:4]
    remainder = 0
    for char in moved:
        for digit in str(int(char, 36)):
            remainder = (remainder * 10 + int(digit)) % 97
    return remainder


def make(bank: str, account: str) -> str:
    return f"AZ{iban.check_digits(bank, account)}{bank}{account}"


def test_the_registry_example_is_valid():
    result = iban.check(REGISTRY_EXAMPLE)
    assert result.valid
    assert result.problems == ()
    assert result.iban == REGISTRY_EXAMPLE
    assert result.formatted == "AZ21 NABZ 0000 0000 1370 1000 1944"
    assert (result.check_digits, result.bank_code, result.account) == (
        "21",
        "NABZ",
        "00000000137010001944",
    )
    assert reference_mod97(REGISTRY_EXAMPLE) == 1


@pytest.mark.parametrize(
    "written",
    [
        "az21 nabz 0000 0000 1370 1000 1944",
        "AZ21-NABZ-0000-0000-1370-1000-1944",
        "  AZ21NABZ00000000137010001944\n",
    ],
)
def test_case_spaces_and_hyphens_are_ignored(written):
    result = iban.check(written)
    assert result.valid
    assert result.iban == REGISTRY_EXAMPLE


@pytest.mark.parametrize(
    ("bank", "account"),
    [("TEST", "00000000000000000001"), ("ABCD", "1A2B3C4D5E6F7G8H9I0J"), ("ZZZZ", "9" * 20)],
)
def test_ibans_built_with_the_check_digit_function_pass_both_checks(bank, account):
    built = make(bank, account)
    assert iban.check(built).valid
    assert reference_mod97(built) == 1


def test_a_changed_digit_or_swapped_digits_fail_the_check():
    changed = REGISTRY_EXAMPLE[:-1] + "5"
    result = iban.check(changed)
    assert not result.valid
    assert result.problems == ("The check digits do not match (the mod-97 test fails).",)
    assert result.formatted == "AZ21 NABZ 0000 0000 1370 1000 1945"
    swapped = REGISTRY_EXAMPLE.replace("37010", "30710")
    assert not iban.check(swapped).valid


def test_another_country_and_the_wrong_length_are_named():
    other = iban.check("GB82WEST12345698765432")
    assert not other.valid
    assert other.problems == (
        "An Azerbaijani IBAN starts with AZ; this one starts with GB.",
        "An Azerbaijani IBAN has 28 characters; this one has 22.",
    )
    assert (other.formatted, other.bank_code) == (None, None)
    short = iban.check(REGISTRY_EXAMPLE[:-1])
    assert short.problems == ("An Azerbaijani IBAN has 28 characters; this one has 27.",)


def test_the_shape_after_az_is_checked():
    # 28 characters, but the bank code has a digit in it.
    result = iban.check("AZ21NAB100000000137010001944")
    assert not result.valid
    assert result.problems == (
        "After AZ come two check digits, a four-letter bank code and 20 letters or digits.",
    )
    assert result.bank_code is None


@pytest.mark.parametrize(
    ("raw", "problem"),
    [
        ("", "The IBAN is empty."),
        ("   ", "The IBAN is empty."),
        ("AZ21 NABZ !!", ONLY_ALNUM),
        ("AZ21NABZ00000000137010001944ə", ONLY_ALNUM),
    ],
)
def test_text_that_is_not_an_iban_is_rejected(raw, problem):
    result = iban.check(raw)
    assert not result.valid
    assert result.problems == (problem,)
    assert result.formatted is None


def test_the_tests_run_without_network_access():
    with pytest.raises(RuntimeError, match="network access is blocked"):
        socket.create_connection(("example.com", 80), timeout=1)
    with socket.socket() as sock, pytest.raises(RuntimeError, match="network access is blocked"):
        sock.connect(("93.184.216.34", 80))
