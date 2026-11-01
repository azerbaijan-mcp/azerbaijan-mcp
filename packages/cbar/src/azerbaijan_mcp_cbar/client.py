"""Fetch and parse the official CBAR daily rates feed (public XML, no authentication)."""

from __future__ import annotations

import asyncio
import math
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Literal

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from . import __version__

FEED_URL = "https://cbar.az/currencies/{day}.xml"

# Azerbaijan has been on UTC+4 all year since 2016. A fixed offset avoids a tzdata dependency
# on Windows.
BAKU = timezone(timedelta(hours=4), "Asia/Baku")

TODAY_TTL_SECONDS = 600
CACHE_SIZE = 128
RETRY_DELAY_SECONDS = 0.5

Kind = Literal["currency", "metal"]

# The feed only carries Azerbaijani names, so English names for the published codes live here.
NAMES_EN = {
    "USD": "US Dollar",
    "EUR": "Euro",
    "AUD": "Australian Dollar",
    "BYN": "Belarusian Ruble",
    "AED": "UAE Dirham",
    "KRW": "South Korean Won",
    "CZK": "Czech Koruna",
    "CNY": "Chinese Yuan",
    "DKK": "Danish Krone",
    "GEL": "Georgian Lari",
    "HKD": "Hong Kong Dollar",
    "INR": "Indian Rupee",
    "GBP": "Pound Sterling",
    "SEK": "Swedish Krona",
    "CHF": "Swiss Franc",
    "ILS": "Israeli Shekel",
    "CAD": "Canadian Dollar",
    "KWD": "Kuwaiti Dinar",
    "KZT": "Kazakhstani Tenge",
    "QAR": "Qatari Riyal",
    "KGS": "Kyrgyzstani Som",
    "HUF": "Hungarian Forint",
    "MDL": "Moldovan Leu",
    "NOK": "Norwegian Krone",
    "UZS": "Uzbekistani Som",
    "PKR": "Pakistani Rupee",
    "PLN": "Polish Zloty",
    "RON": "Romanian Leu",
    "RUB": "Russian Ruble",
    "RSD": "Serbian Dinar",
    "SGD": "Singapore Dollar",
    "SAR": "Saudi Riyal",
    "SDR": "IMF Special Drawing Rights",
    "TRY": "Turkish Lira",
    "TMT": "Turkmenistani Manat",
    "UAH": "Ukrainian Hryvnia",
    "JPY": "Japanese Yen",
    "NZD": "New Zealand Dollar",
    "XAU": "Gold (troy ounce)",
    "XAG": "Silver (troy ounce)",
    "XPT": "Platinum (troy ounce)",
    "XPD": "Palladium (troy ounce)",
}

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_LEADING_NOMINAL = re.compile(r"^\s*\d+(?:[.,]\d+)?\s+")


class FeedError(Exception):
    """The CBAR feed could not be fetched or understood."""


class RatesUnavailable(FeedError):
    """CBAR has no rate sheet for the requested date."""


@dataclass(frozen=True, slots=True)
class Rate:
    code: str
    kind: Kind
    name_az: str
    nominal: Decimal
    value: Decimal  # AZN for `nominal` units; metals: AZN per troy ounce

    @property
    def name_en(self) -> str | None:
        return NAMES_EN.get(self.code)

    @property
    def per_unit(self) -> Decimal:
        return self.value / self.nominal


@dataclass(frozen=True, slots=True)
class RateSheet:
    sheet_date: date
    rates: dict[str, Rate]


def _decimal(text: str | None, what: str) -> Decimal:
    """Read the first number in `text`. Metals carry nominal text such as '1 t.u.'."""
    match = _NUMBER.search(text or "")
    if match is None:
        raise FeedError(f"Cannot read {what} from {text!r}")
    try:
        return Decimal(match.group().replace(",", "."))
    except InvalidOperation as exc:  # pragma: no cover - the pattern only matches numbers
        raise FeedError(f"Cannot read {what} from {text!r}") from exc


def parse_sheet(xml: bytes) -> RateSheet:
    """Parse one CBAR rate sheet. Raises FeedError if it is not what we expect."""
    try:
        root = ElementTree.fromstring(xml)
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        raise FeedError(f"CBAR returned unreadable XML: {exc}") from exc
    if root.tag != "ValCurs":
        raise FeedError(f"Unexpected XML root <{root.tag}>")
    try:
        sheet_date = datetime.strptime(root.get("Date", ""), "%d.%m.%Y").date()
    except ValueError as exc:
        raise FeedError(f"Unreadable sheet date {root.get('Date')!r}") from exc

    rates: dict[str, Rate] = {}
    for group in root.findall("ValType"):
        kind: Kind = "metal" if "metal" in (group.get("Type") or "").lower() else "currency"
        for node in group.findall("Valute"):
            code = (node.get("Code") or "").strip().upper()
            if not code:
                raise FeedError("A <Valute> has no Code")
            nominal = _decimal(node.findtext("Nominal"), f"{code} nominal")
            if nominal <= 0:
                raise FeedError(f"{code} has a non-positive nominal")
            name = " ".join((node.findtext("Name") or "").split())
            rates[code] = Rate(
                code=code,
                kind=kind,
                name_az=_LEADING_NOMINAL.sub("", name),
                nominal=nominal,
                value=_decimal(node.findtext("Value"), f"{code} value"),
            )
    if not rates:
        raise FeedError("CBAR sheet contains no rates")
    return RateSheet(sheet_date=sheet_date, rates=rates)


def parse_day(value: str | None, *, today: date) -> date:
    """Parse YYYY-MM-DD or DD.MM.YYYY. Empty input means `today`."""
    if value is None or not value.strip():
        return today
    text = value.strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date {value!r}: use YYYY-MM-DD")


class CbarClient:
    """Async client for the CBAR rates feed with a small in-memory cache."""

    def __init__(
        self,
        http: httpx.AsyncClient | None = None,
        *,
        today: Callable[[], date] | None = None,
        now: Callable[[], float] = time.monotonic,
        retry_delay: float = RETRY_DELAY_SECONDS,
    ) -> None:
        self._http = http
        self._owns_http = http is None
        self._today = today or (lambda: datetime.now(BAKU).date())
        self._now = now
        self._retry_delay = retry_delay
        self._cache: dict[date, tuple[float, RateSheet]] = {}

    def today(self) -> date:
        """Today's date in Baku."""
        return self._today()

    async def aclose(self) -> None:
        if self._http is not None and self._owns_http:
            await self._http.aclose()
            self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                follow_redirects=True,
                headers={"User-Agent": f"azerbaijan-mcp-cbar/{__version__}"},
            )
        return self._http

    async def get_sheet(self, day: date) -> RateSheet:
        """The sheet CBAR serves for `day`. On weekends and holidays that is an older sheet."""
        cached = self._cache.get(day)
        if cached is not None and cached[0] > self._now():
            return cached[1]
        sheet = await self._fetch(day)
        # Past sheets never change. Today's (or a later day's) can still be revised.
        expires = self._now() + TODAY_TTL_SECONDS if day >= self.today() else math.inf
        if len(self._cache) >= CACHE_SIZE:
            self._cache.pop(next(iter(self._cache)))
        self._cache[day] = (expires, sheet)
        return sheet

    async def _fetch(self, day: date) -> RateSheet:
        url = FEED_URL.format(day=day.strftime("%d.%m.%Y"))
        for attempt in (1, 2):
            try:
                response = await self._client().get(url)
                if response.status_code == 404:
                    raise RatesUnavailable(f"CBAR has no rate sheet for {day.isoformat()}")
                response.raise_for_status()
                return parse_sheet(response.content)
            except httpx.TransportError as exc:
                error: Exception = exc
                retryable = True
            except httpx.HTTPStatusError as exc:
                error = exc
                retryable = exc.response.status_code >= 500
            if attempt == 2 or not retryable:
                raise FeedError(f"CBAR feed request failed: {error}") from error
            await asyncio.sleep(self._retry_delay)
        raise AssertionError("unreachable")  # pragma: no cover
