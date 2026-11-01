"""FastMCP server exposing the official CBAR exchange rates."""

import datetime as dt
import math
from decimal import Decimal
from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from .client import CbarClient, FeedError, Rate, RateSheet, parse_day

SOURCE_URL = "https://cbar.az/currency/rates"
ATTRIBUTION = (
    "Source: Central Bank of the Republic of Azerbaijan (cbar.az), official AZN exchange rates."
)
DISCLAIMER = "Official CBAR reference rates, not bank buy/sell rates."

INSTRUCTIONS = (
    "Official exchange rates of the Central Bank of the Republic of Azerbaijan (CBAR), quoted in "
    "AZN (Azerbaijani manat). Use get_rates for rate tables and convert for amounts. CBAR "
    "publishes no new sheet on weekends and public holidays: responses name the sheet they used. "
    "These are official reference rates, not bank buy/sell rates."
)

READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True}


class RateOut(BaseModel):
    code: str = Field(
        description="Currency code. SDR = IMF Special Drawing Rights; XAU, XAG, XPT, XPD = metals."
    )
    kind: Literal["currency", "metal"]
    name_en: str | None = Field(
        description="English name, or null for a code this server does not know."
    )
    name_az: str = Field(description="Name as published by CBAR, in Azerbaijani.")
    nominal: int | float = Field(
        description="Number of units the published value refers to (1 or 100)."
    )
    value: float = Field(
        description="AZN for `nominal` units as published. Metals: AZN per troy ounce."
    )
    per_unit: float = Field(description="AZN for exactly one unit (value / nominal).")


class RatesResult(BaseModel):
    base: Literal["AZN"] = "AZN"
    requested_date: str = Field(description="The date asked for (YYYY-MM-DD).")
    sheet_date: str = Field(description="The date of the sheet CBAR actually served (YYYY-MM-DD).")
    note: str | None = Field(description="Set when sheet_date differs from requested_date.")
    rates: list[RateOut]
    unknown_codes: list[str] = Field(description="Requested codes CBAR does not publish.")
    source: str
    attribution: str
    disclaimer: str


class ConversionResult(BaseModel):
    amount: float
    from_currency: str
    to_currency: str
    result: float = Field(description="amount converted into to_currency.")
    rate: float = Field(description="Units of to_currency for one unit of from_currency.")
    requested_date: str
    sheet_date: str
    note: str | None
    source: str
    attribution: str
    disclaimer: str


def _number(value: Decimal) -> float:
    """Ten significant digits: plenty for money and free of float noise."""
    return float(format(value, ".10g"))


def _nominal(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


def _rate_out(rate: Rate) -> RateOut:
    return RateOut(
        code=rate.code,
        kind=rate.kind,
        name_en=rate.name_en,
        name_az=rate.name_az,
        nominal=_nominal(rate.nominal),
        value=_number(rate.value),
        per_unit=_number(rate.per_unit),
    )


def _note(requested: dt.date, sheet: RateSheet) -> str | None:
    if sheet.sheet_date == requested:
        return None
    text = (
        f"CBAR has no separate sheet for {requested.isoformat()}; "
        f"its feed returned the sheet dated {sheet.sheet_date.isoformat()}."
    )
    if sheet.sheet_date < requested:
        text += " On weekends and public holidays the last published rates stay in force."
    return text


def _per_unit(code: str, sheet: RateSheet) -> Decimal:
    if code == "AZN":
        return Decimal(1)
    rate = sheet.rates.get(code)
    if rate is None:
        raise ToolError(
            f"Unknown currency code {code!r}. Available: AZN, {', '.join(sorted(sheet.rates))}"
        )
    return rate.per_unit


def create_server(client: CbarClient | None = None) -> FastMCP:
    """Build the server. Tests pass a client wired to a fake transport."""
    cbar = client or CbarClient()
    mcp = FastMCP(name="azerbaijan-mcp-cbar", instructions=INSTRUCTIONS)

    async def load(date: str | None) -> tuple[dt.date, RateSheet]:
        try:
            day = parse_day(date, today=cbar.today())
            return day, await cbar.get_sheet(day)
        except (ValueError, FeedError) as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(annotations=READ_ONLY)
    async def get_rates(
        date: Annotated[
            str | None, Field(description="YYYY-MM-DD. Defaults to today (Baku time).")
        ] = None,
        codes: Annotated[
            list[str] | None,
            Field(description='Only these codes, for example ["USD", "EUR"]. Default: all.'),
        ] = None,
    ) -> RatesResult:
        """Official CBAR exchange rates against the Azerbaijani manat (AZN).

        Returns 38 currencies and 4 precious metals. `value` is AZN for `nominal` units (seven
        currencies are quoted per 100); `per_unit` is AZN for one unit. On weekends and public
        holidays CBAR publishes no new sheet, so `sheet_date` and `note` say which one was used.
        """
        day, sheet = await load(date)
        if codes:
            wanted = list(
                dict.fromkeys(
                    c.strip().upper() for c in codes if c.strip() and c.strip().upper() != "AZN"
                )
            )
            picked = [sheet.rates[c] for c in wanted if c in sheet.rates]
            unknown = [c for c in wanted if c not in sheet.rates]
        else:
            picked = sorted(sheet.rates.values(), key=lambda r: r.kind != "currency")
            unknown = []
        return RatesResult(
            requested_date=day.isoformat(),
            sheet_date=sheet.sheet_date.isoformat(),
            note=_note(day, sheet),
            rates=[_rate_out(r) for r in picked],
            unknown_codes=unknown,
            source=SOURCE_URL,
            attribution=ATTRIBUTION,
            disclaimer=DISCLAIMER,
        )

    @mcp.tool(annotations=READ_ONLY)
    async def convert(
        amount: Annotated[
            float, Field(description="Amount in from_currency (metals: troy ounces).")
        ],
        from_currency: Annotated[
            str, Field(description="Currency code such as USD, EUR, RUB or AZN.")
        ],
        to_currency: Annotated[
            str, Field(description="Currency code such as USD, EUR, RUB or AZN.")
        ],
        date: Annotated[
            str | None, Field(description="YYYY-MM-DD. Defaults to today (Baku time).")
        ] = None,
    ) -> ConversionResult:
        """Convert an amount between two currencies through AZN using official CBAR rates."""
        if not math.isfinite(amount):
            raise ToolError("amount must be a finite number")
        day, sheet = await load(date)
        source, target = from_currency.strip().upper(), to_currency.strip().upper()
        factor = _per_unit(source, sheet) / _per_unit(target, sheet)
        return ConversionResult(
            amount=amount,
            from_currency=source,
            to_currency=target,
            result=_number(Decimal(str(amount)) * factor),
            rate=_number(factor),
            requested_date=day.isoformat(),
            sheet_date=sheet.sheet_date.isoformat(),
            note=_note(day, sheet),
            source=SOURCE_URL,
            attribution=ATTRIBUTION,
            disclaimer=DISCLAIMER,
        )

    return mcp


mcp = create_server()


def main() -> None:
    """Console entry point: serve over stdio."""
    mcp.run(show_banner=False)
