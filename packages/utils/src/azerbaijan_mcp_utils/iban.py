"""Azerbaijani IBAN checks: the ISO 13616 structure and the mod-97 check digits.

Source: the SWIFT IBAN Registry (ISO 13616-1) gives Azerbaijan 28 characters: AZ, two check
digits, a four-letter bank code and 20 letters or digits (BBAN 4!a20!c). The registry's example,
AZ21NABZ00000000137010001944, is in the tests. The same structure is listed at
https://en.wikipedia.org/wiki/International_Bank_Account_Number
"""

import re
from dataclasses import dataclass

COUNTRY = "AZ"
LENGTH = 28
STRUCTURE = re.compile(r"AZ\d{2}[A-Z]{4}[A-Z0-9]{20}")
SEPARATORS = re.compile(r"[\s\-]")


@dataclass(frozen=True, slots=True)
class IbanCheck:
    valid: bool
    iban: str
    formatted: str | None
    check_digits: str | None
    bank_code: str | None
    account: str | None
    problems: tuple[str, ...]


def _mod97(text: str) -> int:
    """Move the first four characters to the end, read letters as 10..35 and divide by 97."""
    digits = "".join(str(int(char, 36)) for char in text[4:] + text[:4])
    return int(digits) % 97


def check_digits(bank_code: str, account: str) -> str:
    """The two check digits that complete a four-letter bank code and a 20-character account."""
    return f"{98 - _mod97(f'{COUNTRY}00{bank_code}{account}'.upper()):02d}"


def check(raw: str) -> IbanCheck:
    """Normalise the text (spaces and hyphens dropped, upper case) and test it."""
    iban = SEPARATORS.sub("", raw).upper()
    if not iban:
        return IbanCheck(False, iban, None, None, None, None, ("The IBAN is empty.",))
    if not (iban.isascii() and iban.isalnum()):
        problem = "An IBAN has only letters and digits; spaces and hyphens are ignored."
        return IbanCheck(False, iban, None, None, None, None, (problem,))
    problems = []
    if not iban.startswith(COUNTRY):
        problems.append(
            f"An Azerbaijani IBAN starts with {COUNTRY}; this one starts with {iban[:2]}."
        )
    if len(iban) != LENGTH:
        problems.append(f"An Azerbaijani IBAN has {LENGTH} characters; this one has {len(iban)}.")
    shaped = STRUCTURE.fullmatch(iban) is not None
    if iban.startswith(COUNTRY) and len(iban) == LENGTH and not shaped:
        problems.append(
            "After AZ come two check digits, a four-letter bank code and 20 letters or digits."
        )
    if shaped and _mod97(iban) != 1:
        problems.append("The check digits do not match (the mod-97 test fails).")
    if not shaped:
        return IbanCheck(False, iban, None, None, None, None, tuple(problems))
    groups = " ".join(iban[start : start + 4] for start in range(0, LENGTH, 4))
    return IbanCheck(not problems, iban, groups, iban[2:4], iban[4:8], iban[8:], tuple(problems))
