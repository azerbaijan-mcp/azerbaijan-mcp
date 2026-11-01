"""Contract tests against the real API. Run with `uv run pytest -m live`.

They send three requests, one per second. DT_AA_001 (population size) is the pinned table.
"""

import pytest

from azerbaijan_mcp_azstat import catalogue, tables
from azerbaijan_mcp_azstat.client import AzstatClient
from azerbaijan_mcp_azstat.errors import NotFound

pytestmark = [pytest.mark.live, pytest.mark.anyio]


@pytest.fixture
async def azstat():
    client = AzstatClient()
    yield client
    await client.aclose()


async def test_the_live_catalogue_still_lists_the_tables(azstat):
    entries = await azstat.catalogue("en")
    assert len(entries) > 1000
    assert "DT_AA_001" in {entry.table_id for entry in entries}
    assert all(entry.name and entry.topic_id for entry in entries)
    assert len(catalogue.topics(entries)) >= 20
    assert catalogue.search(entries, "population")


async def test_the_pinned_table_still_has_the_known_shape(azstat):
    table = await azstat.table("DT_AA_001", "en")
    assert table.name
    assert len(table.dimensions) >= 1
    assert len(table.rows) > 100
    assert not table.ambiguous
    view = tables.overview(table)
    assert view.first_period and view.first_period <= "2000"
    assert view.last_period and view.last_period >= "2020"
    assert any(isinstance(row.value, int | float) for row in table.rows)
    assert tables.select(table, period_from=2020, period_to=2020)


async def test_an_unknown_table_is_still_reported_as_not_found(azstat):
    with pytest.raises(NotFound):
        await azstat.table("DT_ZZ_999", "en")
