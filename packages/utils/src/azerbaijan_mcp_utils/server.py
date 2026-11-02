"""FastMCP server with offline helpers for Azerbaijan."""

import datetime as dt
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from . import iban as iban_rules
from . import phone, production_calendar, translit, words
from .models import (
    AmountInWords,
    Holiday,
    HolidayYear,
    IbanCheck,
    NonWorkingDay,
    PhoneCheck,
    Transliteration,
    WorkingDays,
)

SOURCES = {
    "iban": "ISO 13616 (SWIFT IBAN Registry): Azerbaijan, 28 characters, mod-97 check digits.",
    "phone": "National Numbering Plan of Azerbaijan (ITU Operational Bulletin No. 1162, 2018).",
    "words": "Azerbaijani, English and Russian numerals; the README lists the conventions.",
    "translit": "The 32-letter Azerbaijani Latin alphabet and the Cyrillic alphabet of 1958-1991.",
}
INSTRUCTIONS = (
    "Offline helpers for Azerbaijan; nothing is sent over the network. validate_iban checks an "
    "Azerbaijani IBAN, format_phone normalises a phone number to +994, azn_in_words writes an "
    "amount in manat in Azerbaijani, English or Russian, transliterate converts between the "
    "Latin and the 1958 Cyrillic alphabet, holidays lists a year's official non-working days "
    "and working_days counts working days between two dates. The calendar covers only the years "
    "whose official decisions are loaded; other years are refused, not guessed."
)
OFFLINE = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
MAX_TEXT = 10_000
Lang = Literal["az", "en", "ru"]
Week = Literal["five_day", "six_day"]
Direction = Literal["latin_to_cyrillic", "cyrillic_to_latin"]


def _date(value: str, name: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as exc:
        raise ToolError(f"{name} must be a date such as 2026-03-27.") from exc


def _holiday_days(calendar: production_calendar.Calendar) -> list[Holiday]:
    by_date: dict[dt.date, list[production_calendar.Entry]] = {}
    for entry in calendar.entries:
        by_date.setdefault(entry.date, []).append(entry)
    return [
        Holiday(
            date=day.isoformat(),
            weekday=production_calendar.WEEKDAYS[day.weekday()],
            names_az=[entry.name_az for entry in entries],
            names_en=[entry.name_en for entry in entries],
            kinds=[entry.kind for entry in entries],
        )
        for day, entries in sorted(by_date.items())
    ]


def create_server() -> FastMCP:
    """Build the server. It has no client to fake: every tool is a pure function."""
    mcp = FastMCP(name="azerbaijan-mcp-utils", instructions=INSTRUCTIONS)

    @mcp.tool(annotations=OFFLINE)
    def validate_iban(
        iban: Annotated[str, Field(max_length=100, description="An IBAN, with or without spaces.")],
    ) -> IbanCheck:
        """Check an Azerbaijani IBAN: AZ, 28 characters, the structure and the mod-97 check digits.

        A valid IBAN has the right shape and check digits. That does not mean the account exists.
        """
        result = iban_rules.check(iban)
        return IbanCheck(
            valid=result.valid,
            iban=result.iban,
            formatted=result.formatted,
            check_digits=result.check_digits,
            bank_code=result.bank_code,
            account=result.account,
            problems=list(result.problems),
            source=SOURCES["iban"],
        )

    @mcp.tool(annotations=OFFLINE)
    def format_phone(
        number: Annotated[
            str,
            Field(
                max_length=40, description="A phone number: +994 50 123 45 67, 050 123 45 67, ..."
            ),
        ],
    ) -> PhoneCheck:
        """Normalise an Azerbaijani phone number to +994 and say if it is mobile or landline."""
        result = phone.check(number)
        return PhoneCheck(
            valid_format=result.valid_format,
            e164=result.e164,
            international=result.international,
            national=result.national,
            kind=result.kind,
            area=result.area,
            problems=list(result.problems),
            notes=list(result.notes),
            source=SOURCES["phone"],
        )

    @mcp.tool(annotations=OFFLINE)
    def azn_in_words(
        amount: Annotated[
            str | int | float,
            Field(description="An amount in manat with at most two decimals, for example 1234.56."),
        ],
        lang: Annotated[Lang, Field(description="az, en or ru.")] = "az",
        bir_min: Annotated[
            bool,
            Field(description="Azerbaijani only: write 'bir min' for 1000, as many documents do."),
        ] = False,
    ) -> AmountInWords:
        """Write an amount in manat and qəpik in words, for a contract or an invoice.

        The amount is exact: more than two decimals is refused, never rounded. A string such as
        "1234.56" is safest; a float is read as its shortest text.
        """
        try:
            result = words.amount_in_words(amount, lang, bir_min)
        except words.AmountError as exc:
            raise ToolError(str(exc)) from exc
        return AmountInWords(
            amount=result.decimal,
            lang=lang,
            text=result.text,
            manat=result.manat,
            qepik=result.qepik,
            source=SOURCES["words"],
        )

    @mcp.tool(annotations=OFFLINE)
    def transliterate(
        text: Annotated[str, Field(max_length=MAX_TEXT, description="The text to convert.")],
        direction: Annotated[
            Direction, Field(description="latin_to_cyrillic or cyrillic_to_latin.")
        ],
    ) -> Transliteration:
        """Convert Azerbaijani text between the Latin alphabet and the Cyrillic one of 1958-1991.

        The 32 letters of each alphabet correspond one to one. Other letters, for example
        letters only Russian uses, are left as they are and listed in `unchanged`.
        """
        result, unchanged = translit.transliterate(text, direction)
        notes = []
        if unchanged:
            notes.append("Letters outside the 32-letter tables were left unchanged.")
        return Transliteration(
            direction=direction,
            result=result,
            unchanged=unchanged,
            notes=notes,
            source=SOURCES["translit"],
        )

    @mcp.tool(annotations=OFFLINE)
    def holidays(
        year: Annotated[int, Field(ge=1900, le=2200, description="A year with a loaded calendar.")],
    ) -> HolidayYear:
        """The official non-working days of a year, with the decisions they come from.

        Years are loaded from the Ministry of Labour's production calendar and the Cabinet decision
        on the Novruz, Ramadan and Qurban days. A year whose decisions are not loaded is refused.
        """
        try:
            calendar = production_calendar.calendar_for(year)
        except production_calendar.CalendarError as exc:
            raise ToolError(str(exc)) from exc
        return HolidayYear(
            year=year,
            decision=calendar.decision,
            url=calendar.url,
            cabinet_decisions=list(calendar.cabinet_decisions),
            days=_holiday_days(calendar),
            rest_days={
                week: [day.isoformat() for day in sorted(calendar.rest_days[week])]
                for week in production_calendar.WEEKS
            },
            five_day_working_days=calendar.official_totals["five_day_working_days"],
            notes=[
                "Saturday and Sunday (five-day week) or Sunday (six-day week) are weekly rest "
                "days and are not listed.",
            ],
        )

    @mcp.tool(annotations=OFFLINE)
    def working_days(
        start: Annotated[str, Field(description="First day, as 2026-03-16.")],
        end: Annotated[str, Field(description="Last day, included, as 2026-03-31.")],
        week: Annotated[
            Week, Field(description="five_day: Saturday and Sunday off. six_day: Sunday off.")
        ] = "five_day",
    ) -> WorkingDays:
        """Count the working days from start to end, both included, by the official calendars.

        Weekly rest days, holidays and the rest days moved because of holidays do not count. Both
        dates must fall in years whose calendars are loaded.
        """
        first, last = _date(start, "start"), _date(end, "end")
        try:
            span = production_calendar.working_days(first, last, week)
            years = range(first.year, last.year + 1)
            sources = [production_calendar.calendar_for(year).url for year in years]
        except production_calendar.CalendarError as exc:
            raise ToolError(str(exc)) from exc
        return WorkingDays(
            start=first.isoformat(),
            end=last.isoformat(),
            week=week,
            calendar_days=span.calendar_days,
            working_days=span.working_days,
            non_working_days=[
                NonWorkingDay(
                    date=item.date.isoformat(),
                    weekday=production_calendar.WEEKDAYS[item.date.weekday()],
                    reasons=list(item.reasons),
                )
                for item in span.non_working
            ],
            sources=sources,
            notes=[],
        )

    return mcp


mcp = create_server()


def main() -> None:
    """Console entry point: serve over stdio."""
    mcp.run(show_banner=False)
