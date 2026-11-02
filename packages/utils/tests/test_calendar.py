import datetime as dt

import pytest

from azerbaijan_mcp_utils import production_calendar as pc

KINDS = {"fixed", "decree", "mourning", "election"}
HOLIDAY_KINDS = {"fixed", "decree"}
FIVE_DAY_REST = "Rest day moved from a weekly rest day that fell on a holiday"


def d(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def count_working_days(year: int, week: str = "five_day") -> int:
    day = dt.date(year, 1, 1)
    total = 0
    while day.year == year:
        total += pc.day_status(day, week).working
        day += dt.timedelta(days=1)
    return total


def test_both_years_are_loaded():
    assert 2025 in pc.supported_years()
    assert 2026 in pc.supported_years()


@pytest.mark.parametrize("year", pc.supported_years())
def test_a_years_file_reproduces_the_official_working_day_total(year):
    calendar = pc.calendar_for(year)
    assert count_working_days(year) == calendar.official_totals["five_day_working_days"]


@pytest.mark.parametrize("year", pc.supported_years())
def test_a_years_file_is_consistent_with_the_ministrys_counts(year):
    calendar = pc.calendar_for(year)
    totals = calendar.official_totals
    holidays = [entry for entry in calendar.entries if entry.kind in HOLIDAY_KINDS]
    others = [entry for entry in calendar.entries if entry.kind not in HOLIDAY_KINDS]
    assert len(holidays) == totals["holidays"]
    assert len(others) == totals["other_days"]
    assert len(holidays) - len({entry.date for entry in holidays}) == totals["overlapping_holidays"]
    assert calendar.year == year


@pytest.mark.parametrize("year", pc.supported_years())
def test_a_years_dates_are_in_that_year_and_not_repeated(year):
    calendar = pc.calendar_for(year)
    assert {entry.kind for entry in calendar.entries} <= KINDS
    assert all(entry.date.year == year for entry in calendar.entries)
    keys = [(entry.date, entry.name_az) for entry in calendar.entries]
    assert len(keys) == len(set(keys))
    assert all(entry.name_az and entry.name_en for entry in calendar.entries)
    for week in pc.WEEKS:
        days = calendar.rest_days[week]
        assert days
        assert all(day.year == year for day in days)
        assert not any(day.weekday() >= 5 for day in days if week == "five_day")


@pytest.mark.parametrize("year", pc.supported_years())
def test_a_year_names_the_decision_it_rests_on(year):
    calendar = pc.calendar_for(year)
    assert calendar.decision.startswith("Decision of the Collegium")
    assert calendar.url.startswith("https://sosial.gov.az/")
    assert any("Novruz, Ramadan and Qurban" in decision for decision in calendar.cabinet_decisions)


def test_the_2026_decisions_are_named():
    calendar = pc.calendar_for(2026)
    assert "11 December 2025, No. 3-17/3-5-31/2025" in calendar.decision
    assert "2 December 2025, No. 362" in calendar.cabinet_decisions[0]


def test_the_2025_decisions_are_named():
    calendar = pc.calendar_for(2025)
    assert "16 December 2024, No. 3-17/3-5-31/2024" in calendar.decision
    assert "11 December 2024, No. 521" in calendar.cabinet_decisions[0]
    assert any("28 November 2024, No. 499" in decision for decision in calendar.cabinet_decisions)


def test_a_moved_rest_day_is_not_a_working_day_in_the_week_it_applies_to():
    friday = pc.day_status(d("2026-03-27"))
    assert (friday.working, friday.reasons) == (False, (FIVE_DAY_REST,))
    assert not pc.day_status(d("2026-03-27"), "six_day").working
    monday = d("2026-03-30")
    assert not pc.day_status(monday, "five_day").working
    assert pc.day_status(monday, "six_day").working


def test_weekends_follow_the_week():
    saturday, sunday = d("2026-02-14"), d("2026-02-15")
    assert pc.day_status(saturday).reasons == ("Saturday: weekly rest day",)
    assert pc.day_status(sunday).reasons == ("Sunday: weekly rest day",)
    assert pc.day_status(saturday, "six_day").working
    assert pc.day_status(sunday, "six_day").reasons == ("Sunday: weekly rest day",)


def test_overlapping_holidays_and_weekends_list_every_reason():
    assert pc.day_status(d("2026-03-21")).reasons == (
        "Saturday: weekly rest day",
        "Novruz",
        "Ramadan Bayram (Eid al-Fitr)",
    )
    assert pc.day_status(d("2026-03-21"), "six_day").reasons == (
        "Novruz",
        "Ramadan Bayram (Eid al-Fitr)",
    )
    assert pc.day_status(d("2026-05-28")).reasons == (
        "Qurban Bayram (Eid al-Adha)",
        "Independence Day",
    )


def test_the_day_of_national_mourning_and_a_voting_day_are_not_working_days():
    assert pc.day_status(d("2026-01-20")).reasons == ("Day of National Mourning",)
    voting = pc.day_status(d("2025-01-29"))
    assert not voting.working
    assert voting.reasons[0].startswith("Municipal elections day")


def test_an_ordinary_day_is_a_working_day():
    status = pc.day_status(d("2026-03-31"))
    assert (status.working, status.reasons) == (True, ())


def test_2025_rest_days_moved_by_the_cabinet_decision():
    assert not pc.day_status(d("2025-01-03")).working
    assert not pc.day_status(d("2025-04-01")).working
    assert pc.day_status(d("2025-01-03"), "six_day").working
    assert not pc.day_status(d("2025-04-01"), "six_day").working


def test_counting_working_days_in_a_range():
    span = pc.working_days(d("2026-03-16"), d("2026-03-31"))
    assert (span.calendar_days, span.working_days) == (16, 5)
    assert len(span.non_working) == 11
    assert span.non_working[0].date == d("2026-03-20")
    assert span.non_working[0].reasons == ("Novruz", "Ramadan Bayram (Eid al-Fitr)")
    assert pc.working_days(d("2026-03-16"), d("2026-03-31"), "six_day").working_days == 7


def test_a_range_can_cross_a_new_year_and_a_single_day_counts():
    assert pc.working_days(d("2025-12-29"), d("2026-01-05")).working_days == 3
    assert pc.working_days(d("2026-03-31"), d("2026-03-31")).working_days == 1
    assert pc.working_days(d("2026-03-27"), d("2026-03-27")).working_days == 0


def test_a_whole_year_adds_up_to_the_official_total():
    span = pc.working_days(d("2026-01-01"), d("2026-12-31"))
    assert (span.calendar_days, span.working_days) == (365, 241)
    assert len(span.non_working) == 365 - 241


def test_a_year_without_a_calendar_is_refused():
    with pytest.raises(
        pc.CalendarError, match=r"no official calendar for 2099.*Calendars loaded: 2025"
    ):
        pc.calendar_for(2099)
    with pytest.raises(pc.CalendarError, match="2099"):
        pc.day_status(d("2099-01-01"))
    with pytest.raises(pc.CalendarError, match="2099"):
        pc.working_days(d("2099-01-01"), d("2099-01-02"))


def test_bad_ranges_and_weeks_are_refused():
    with pytest.raises(pc.CalendarError, match="end date is before"):
        pc.working_days(d("2026-03-31"), d("2026-03-16"))
    with pytest.raises(pc.CalendarError, match="longer than 3660 days"):
        pc.working_days(d("2000-01-01"), d("2026-01-01"))
    with pytest.raises(pc.CalendarError, match="week must be one of five_day, six_day"):
        pc.day_status(d("2026-03-31"), "four_day")
