"""Contract test against the real CBAR feed. Run with `uv run pytest -m live`."""

import pytest

from azerbaijan_mcp_cbar.client import CbarClient

pytestmark = [pytest.mark.live, pytest.mark.anyio]


async def test_the_live_feed_still_parses():
    client = CbarClient()
    try:
        sheet = await client.get_sheet(client.today())
    finally:
        await client.aclose()
    currencies = [r for r in sheet.rates.values() if r.kind == "currency"]
    metals = [r for r in sheet.rates.values() if r.kind == "metal"]
    assert "USD" in sheet.rates
    assert len(currencies) >= 30
    assert {"XAU", "XAG"} <= {r.code for r in metals}
    assert all(r.value > 0 and r.nominal > 0 for r in sheet.rates.values())
