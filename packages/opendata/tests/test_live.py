"""Contract tests against the real portal. Run with `uv run pytest -m live`.

They send about six requests, one per second.
"""

import pytest

from azerbaijan_mcp_opendata import datasets, preview
from azerbaijan_mcp_opendata.client import OpenDataClient

pytestmark = [pytest.mark.live, pytest.mark.anyio]


@pytest.fixture
async def portal():
    client = OpenDataClient()
    yield client
    await client.aclose()


async def test_the_live_search_still_has_the_expected_shape(portal):
    result = await portal.search(q="population", fq=[], rows=3, start=0, sort="score desc")
    assert result["count"] > 0
    found = [datasets.summarize(raw, "en") for raw in result["results"]]
    assert found
    assert all(item.id and item.name and item.title and item.url for item in found)


async def test_the_live_facets_list_publishers_topics_and_licences(portal):
    result = await portal.facets()
    organizations = {item.name for item in datasets.facet_items(result, "organization")}
    groups = {item.name for item in datasets.facet_items(result, "groups")}
    licences = {item.name for item in datasets.facet_items(result, "license_id")}
    assert "dsk" in organizations
    assert "economics" in groups
    assert "cc-zero" in licences


async def test_a_live_json_file_can_be_found_and_previewed(portal):
    found = await portal.search(
        q=None,
        fq=['organization:"dsk"', 'res_format:"JSON"'],
        rows=1,
        start=0,
        sort="metadata_modified desc",
    )
    record = await portal.show(found["results"][0]["name"])
    info = datasets.detail(record, "en", portal.host_allowed, "test")
    target = next(item for item in info.resources if item.format == "JSON" and item.previewable)
    content, _ = await portal.fetch_resource(target.url)
    parsed = preview.preview_json(content, rows=5)
    assert parsed["total_records"] > 0
    assert parsed["records"]
