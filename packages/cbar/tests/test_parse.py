from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from azerbaijan_mcp_cbar.client import FeedError, parse_day, parse_sheet

FIXTURE = Path(__file__).parent / "fixtures" / "rates-2026-10-30.xml"
TODAY = date(2026, 11, 1)


@pytest.fixture(scope="module")
def sheet():
    return parse_sheet(FIXTURE.read_bytes())


def test_sheet_date_and_counts(sheet):
    assert sheet.sheet_date == date(2026, 10, 30)
    currencies = [r for r in sheet.rates.values() if r.kind == "currency"]
    metals = sorted(r.code for r in sheet.rates.values() if r.kind == "metal")
    assert len(currencies) == 38
    assert metals == ["XAG", "XAU", "XPD", "XPT"]


def test_nominal_and_per_unit(sheet):
    usd, rub = sheet.rates["USD"], sheet.rates["RUB"]
    assert (usd.nominal, usd.value, usd.per_unit) == (1, Decimal("1.7"), Decimal("1.7"))
    assert (rub.nominal, rub.value) == (100, Decimal("2.0923"))
    assert rub.per_unit == Decimal("0.020923")


def test_seven_currencies_are_quoted_per_100(sheet):
    per_100 = {code for code, rate in sheet.rates.items() if rate.nominal == 100}
    assert per_100 == {"JPY", "KRW", "KZT", "HUF", "UZS", "PKR", "RUB"}


def test_metal_nominal_is_text_in_the_feed(sheet):
    gold = sheet.rates["XAU"]
    assert gold.nominal == 1  # the feed says "1 t.u." (troy ounce)
    assert gold.value == Decimal("6796.43")


def test_names_drop_the_nominal_prefix(sheet):
    assert sheet.rates["RUB"].name_az == "Rusiya rublu"
    assert sheet.rates["USD"].name_az == "ABŞ dolları"


def test_every_published_code_has_an_english_name(sheet):
    assert [c for c, r in sheet.rates.items() if not r.name_en] == []


@pytest.mark.parametrize(
    "xml",
    [
        b"not xml",
        b"<Other/>",
        b'<ValCurs Date="bad"/>',
        b'<ValCurs Date="30.10.2026"/>',
        b'<ValCurs Date="30.10.2026"><ValType Type="x"><Valute Code="USD">'
        b"<Nominal>0</Nominal><Value>1</Value></Valute></ValType></ValCurs>",
    ],
)
def test_malformed_feed_raises(xml):
    with pytest.raises(FeedError):
        parse_sheet(xml)


def test_entity_declarations_are_refused():
    xml = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]>'
        b'<ValCurs Date="30.10.2026">&a;</ValCurs>'
    )
    with pytest.raises(FeedError):
        parse_sheet(xml)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, TODAY),
        ("", TODAY),
        ("2026-10-30", date(2026, 10, 30)),
        ("30.10.2026", date(2026, 10, 30)),
        (" 2026-10-30 ", date(2026, 10, 30)),
    ],
)
def test_parse_day(text, expected):
    assert parse_day(text, today=TODAY) == expected


def test_parse_day_rejects_other_formats():
    with pytest.raises(ValueError, match="Invalid date"):
        parse_day("yesterday", today=TODAY)
