"""The official production calendar: non-working days and working days, year by year.

Each file in `data/` copies one year's calendar from the Ministry of Labour and Social Protection
of the Population (https://sosial.gov.az/faydali/istehsalat-teqvimi): the days that are not
working days, the rest days moved under Labour Code article 105 and the Cabinet of Ministers
decision that fixes the Novruz, Ramadan and Qurban days. A file also keeps the official yearly
total of working days, and the tests check that the file reproduces it. A year without a file is
refused, never guessed. The yearly update procedure is in the package README.
"""

import datetime as dt
import json
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

Week = Literal["five_day", "six_day"]
WEEKS = ("five_day", "six_day")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
MAX_RANGE_DAYS = 3660
FILE_PREFIX = "calendar_"


class CalendarError(ValueError):
    """The question cannot be answered from the official calendars."""


@dataclass(frozen=True, slots=True)
class Entry:
    date: dt.date
    kind: str
    name_az: str
    name_en: str


@dataclass(frozen=True, slots=True)
class Calendar:
    year: int
    decision: str
    url: str
    cabinet_decisions: tuple[str, ...]
    entries: tuple[Entry, ...]
    rest_days: dict[str, frozenset[dt.date]]
    official_totals: dict[str, int]


@dataclass(frozen=True, slots=True)
class DayStatus:
    date: dt.date
    working: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Range:
    start: dt.date
    end: dt.date
    week: str
    calendar_days: int
    working_days: int
    non_working: tuple[DayStatus, ...]


def _data():
    return resources.files("azerbaijan_mcp_utils").joinpath("data")


@cache
def supported_years() -> tuple[int, ...]:
    names = [item.name for item in _data().iterdir()]
    years = [
        int(name.removeprefix(FILE_PREFIX).removesuffix(".json"))
        for name in names
        if name.startswith(FILE_PREFIX) and name.endswith(".json")
    ]
    return tuple(sorted(years))


@cache
def calendar_for(year: int) -> Calendar:
    if year not in supported_years():
        loaded = ", ".join(str(item) for item in supported_years())
        raise CalendarError(
            f"There is no official calendar for {year} in this server. Calendars loaded: {loaded}. "
            "A year is added when its decisions are published, usually in December."
        )
    raw = json.loads(_data().joinpath(f"{FILE_PREFIX}{year}.json").read_text(encoding="utf-8"))
    entries = tuple(
        Entry(dt.date.fromisoformat(item["date"]), item["kind"], item["name_az"], item["name_en"])
        for item in raw["entries"]
    )
    rest_days = {
        week: frozenset(dt.date.fromisoformat(day) for day in raw["rest_days"][week])
        for week in WEEKS
    }
    return Calendar(
        year=raw["year"],
        decision=raw["decision"],
        url=raw["url"],
        cabinet_decisions=tuple(raw["cabinet_decisions"]),
        entries=entries,
        rest_days=rest_days,
        official_totals=raw["official_totals"],
    )


def _weekly_rest(day: dt.date, week: str) -> bool:
    """Saturday and Sunday in a five-day week, Sunday alone in a six-day week."""
    return day.weekday() >= 5 if week == "five_day" else day.weekday() == 6


def day_status(day: dt.date, week: str = "five_day") -> DayStatus:
    if week not in WEEKS:
        raise CalendarError(f"week must be one of {', '.join(WEEKS)}.")
    calendar = calendar_for(day.year)
    reasons = []
    if _weekly_rest(day, week):
        reasons.append(f"{WEEKDAYS[day.weekday()]}: weekly rest day")
    reasons += [entry.name_en for entry in calendar.entries if entry.date == day]
    if day in calendar.rest_days[week]:
        reasons.append("Rest day moved from a weekly rest day that fell on a holiday")
    return DayStatus(day, not reasons, tuple(reasons))


def working_days(start: dt.date, end: dt.date, week: str = "five_day") -> Range:
    """Working days from start to end, both included, by the official calendars."""
    if end < start:
        raise CalendarError("The end date is before the start date.")
    if (end - start).days + 1 > MAX_RANGE_DAYS:
        raise CalendarError(f"The range is longer than {MAX_RANGE_DAYS} days.")
    statuses = [
        day_status(start + dt.timedelta(days=offset), week)
        for offset in range((end - start).days + 1)
    ]
    return Range(
        start=start,
        end=end,
        week=week,
        calendar_days=len(statuses),
        working_days=sum(status.working for status in statuses),
        non_working=tuple(status for status in statuses if not status.working),
    )
