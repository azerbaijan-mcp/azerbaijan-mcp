"""Tool output models."""

from typing import Literal

from pydantic import BaseModel, Field


class IbanCheck(BaseModel):
    valid: bool = Field(
        description="True when the IBAN has the Azerbaijani shape and the right check digits."
    )
    iban: str = Field(description="The IBAN as read: upper case, without spaces and hyphens.")
    formatted: str | None = Field(
        description="In groups of four; null when the text is not shaped like an AZ IBAN."
    )
    check_digits: str | None
    bank_code: str | None = Field(description="The four-letter bank code.")
    account: str | None = Field(description="The 20-character account part.")
    problems: list[str]
    source: str


class PhoneCheck(BaseModel):
    valid_format: bool = Field(
        description="True for a nine-digit Azerbaijani number; it may still be unused."
    )
    e164: str | None = Field(description="For example +994501234567.")
    international: str | None = Field(description="For example +994 50 123 45 67.")
    national: str | None = Field(description="With the trunk prefix, for example 050 123 45 67.")
    kind: Literal["mobile", "landline", "unknown"] | None = Field(
        description="From the prefix. The operator is not reported: numbers can change network."
    )
    area: str | None = Field(description="The area of a landline number.")
    problems: list[str]
    notes: list[str]
    source: str


class AmountInWords(BaseModel):
    amount: str = Field(description="The amount as read, with two decimals, for example 1234.56.")
    lang: Literal["az", "en", "ru"]
    text: str
    manat: int
    qepik: int
    source: str


class Transliteration(BaseModel):
    direction: Literal["latin_to_cyrillic", "cyrillic_to_latin"]
    result: str
    unchanged: str = Field(
        description="Letters that are not in the 32-letter tables and were left as they were."
    )
    notes: list[str]
    source: str


class Holiday(BaseModel):
    date: str
    weekday: str
    names_az: list[str] = Field(description="As the Ministry's calendar writes them.")
    names_en: list[str] = Field(description="Translations.")
    kinds: list[Literal["fixed", "decree", "mourning", "election"]] = Field(
        description="fixed: set by the Labour Code. decree: Novruz, Ramadan or Qurban, set by the "
        "Cabinet of Ministers decision. mourning: the Day of National Mourning. election: a "
        "voting day, non-working where the vote is held."
    )


class HolidayYear(BaseModel):
    year: int
    decision: str = Field(description="The Ministry's decision the calendar comes from.")
    url: str
    cabinet_decisions: list[str] = Field(description="The decisions the movable days rest on.")
    days: list[Holiday]
    rest_days: dict[str, list[str]] = Field(
        description="Extra rest days that replace weekly rest days that fell on holidays, for the "
        "five_day and the six_day week."
    )
    five_day_working_days: int = Field(
        description="The official number of working days in the year."
    )
    notes: list[str]


class NonWorkingDay(BaseModel):
    date: str
    weekday: str
    reasons: list[str]


class WorkingDays(BaseModel):
    start: str
    end: str
    week: Literal["five_day", "six_day"]
    calendar_days: int
    working_days: int
    non_working_days: list[NonWorkingDay]
    sources: list[str]
    notes: list[str]
