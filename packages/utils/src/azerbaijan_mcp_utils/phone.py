"""Azerbaijani telephone numbers: +994 normalisation and the number type.

Source: the National Numbering Plan of Azerbaijan (ITU Operational Bulletin No. 1162 of
15 December 2018; regulator: the Ministry of Digital Development and Transport), as summarised at
https://en.wikipedia.org/wiki/Telephone_numbers_in_Azerbaijan. National numbers have nine digits,
a two-digit mobile prefix or area code and seven digits. The trunk prefix is 0 and the country code
is 994. Mobile numbers can move between networks, so the operator is never reported.
"""

import re
from dataclasses import dataclass

COUNTRY_CODE = "994"
NATIONAL_LENGTH = 9
MOBILE_PREFIXES = frozenset({"10", "50", "51", "55", "60", "70", "77", "99"})
AREAS = {
    "12": "Baku",
    "18": "Sumqayit",
    "20": "Baku region",
    "21": "Shirvan region",
    "22": "Ganja region",
    "23": "Quba region",
    "24": "Shaki region",
    "25": "Lankaran region",
    "26": "Shusha region",
    "36": "Nakhchivan Autonomous Republic",
}
ALLOWED = re.compile(r"\+?[\d\s().\-]+")


@dataclass(frozen=True, slots=True)
class PhoneCheck:
    valid_format: bool
    e164: str | None
    international: str | None
    national: str | None
    kind: str | None
    area: str | None
    problems: tuple[str, ...]
    notes: tuple[str, ...]


def _failure(*problems: str) -> PhoneCheck:
    return PhoneCheck(False, None, None, None, None, None, problems, ())


def check(raw: str) -> PhoneCheck:
    text = raw.strip()
    if not ALLOWED.fullmatch(text):
        return _failure("A phone number has digits and at most + ( ) . - and spaces.")
    digits = re.sub(r"\D", "", text)
    international = text.startswith("+")
    if not international and digits.startswith("00"):
        international, digits = True, digits[2:]
    if international:
        if not digits.startswith(COUNTRY_CODE):
            return _failure(
                f"This is not an Azerbaijani number: it must start with +{COUNTRY_CODE}."
            )
        national = digits[len(COUNTRY_CODE) :]
    elif digits.startswith(COUNTRY_CODE) and len(digits) == len(COUNTRY_CODE) + NATIONAL_LENGTH:
        national = digits[len(COUNTRY_CODE) :]
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits
    if len(national) != NATIONAL_LENGTH:
        return _failure(
            f"An Azerbaijani number has {NATIONAL_LENGTH} digits after +{COUNTRY_CODE} or the "
            f"leading 0; this one has {len(national)}."
        )
    prefix, rest = national[:2], national[2:]
    spaced = f"{prefix} {rest[:3]} {rest[3:5]} {rest[5:]}"
    kind = "mobile" if prefix in MOBILE_PREFIXES else "landline" if prefix in AREAS else "unknown"
    notes = ()
    if kind == "unknown":
        notes = (
            f"The prefix {prefix} is not in the numbering plan this server knows. The number may "
            "be new or wrong.",
        )
    return PhoneCheck(
        valid_format=True,
        e164=f"+{COUNTRY_CODE}{national}",
        international=f"+{COUNTRY_CODE} {spaced}",
        national=f"0{spaced}",
        kind=kind,
        area=AREAS.get(prefix),
        problems=(),
        notes=notes,
    )
