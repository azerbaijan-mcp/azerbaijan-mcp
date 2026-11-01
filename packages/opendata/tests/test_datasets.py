import copy
import json

import pytest

from azerbaijan_mcp_opendata import datasets
from azerbaijan_mcp_opendata.client import OpenDataClient
from azerbaijan_mcp_opendata.models import License, Organization

ATTRIBUTION = "Source: test"
ENGLISH_TITLE = "Income and expenditure of population (current prices, million manat)"


@pytest.fixture
def record(show_record):
    return copy.deepcopy(show_record)


def allowed(url: str) -> bool:
    return OpenDataClient().host_allowed(url)


def test_summary_follows_the_requested_language_and_falls_back(record):
    assert datasets.summarize(record, "en").title == ENGLISH_TITLE
    assert datasets.summarize(record, "az").title.startswith("Əhalinin gəlirləri")
    assert datasets.summarize(record, "ru").title == ENGLISH_TITLE
    record["title_translated"] = {}
    assert datasets.summarize(record, "en").title == record["title"]


def test_summary_fields(record, ids):
    summary = datasets.summarize(record, "en")
    assert (summary.id, summary.name) == (ids.dataset, ids.name)
    assert summary.organization == Organization(
        name="dsk", title="Azərbaycan Respublikasının Dövlət Statistika Komitəsi"
    )
    assert [(g.name, g.title) for g in summary.groups] == [("economics", "İqtisadiyyat")]
    assert summary.license == License(id="cc-zero", title="Creative Commons CCZero", known=True)
    assert summary.formats == ["CSV", "JSON"]
    assert summary.num_resources == 3
    assert summary.url == f"https://opendata.az/en/dataset/{ids.name}"


def test_description_is_flattened_and_clipped(record):
    record["notes_translated"] = {"en": "first\n\n  line " + "word " * 200}
    description = datasets.summarize(record, "en").description
    assert description.startswith("first line word")
    assert len(description) == datasets.SUMMARY_CHARS
    assert description.endswith("…")
    assert len(datasets.detail(record, "en", allowed, ATTRIBUTION).description) > len(description)


def test_missing_organization_and_formats_are_tolerated(record):
    record["organization"] = None
    record["resources"][0]["format"] = ".csv"
    record["resources"][1]["format"] = ""
    summary = datasets.summarize(record, "en")
    assert summary.organization is None
    assert summary.formats == ["CSV", "JSON"]


@pytest.mark.parametrize("license_id", ["", "notspecified"])
def test_an_unstated_licence_is_flagged(record, license_id):
    record["license_id"] = license_id
    info = datasets.detail(record, "en", allowed, ATTRIBUTION)
    assert info.license.known is False
    assert any("No licence is stated" in note for note in info.notes)


def test_detail_lists_files_and_whether_they_can_be_previewed(record, ids):
    record["resources"].append(
        {"id": "x1", "format": "XLSX", "url": "https://opendata.az/a.xlsx", "size": "12 KB"}
    )
    record["resources"].append({"id": "x2", "format": "CSV", "url": "https://example.com/a.csv"})
    record["resources"].append({"id": "x3", "format": "", "url": "https://opendata.az/blob"})
    info = datasets.detail(record, "en", allowed, ATTRIBUTION)
    files = {item.id: item for item in info.resources}
    assert files[ids.portal_csv].previewable is True
    assert (files[ids.portal_csv].size_bytes, files[ids.azstat_csv].size_bytes) == (3223, None)
    assert files[ids.azstat_json].previewable is True
    assert files["x1"].previewable is False
    assert files["x1"].size_bytes is None
    assert files["x1"].preview_note == "XLSX files are not previewed; use the link."
    assert "outside the allowed hosts" in files["x2"].preview_note
    assert files["x3"].preview_note == "Files of unknown type are not previewed; use the link."
    assert (info.tags, info.source, info.attribution) == (
        ["national_accounts"],
        info.url,
        ATTRIBUTION,
    )
    assert info.notes == []


def test_nothing_about_individuals_reaches_the_output(record):
    personal = {
        "author": "Jane Doe",
        "author_email": "jane@example.org",
        "maintainer": "John Roe",
        "maintainer_email": "john@example.org",
        "author_translated": {"az": "Jane Doe"},
        "maintainer_translated": {"en": "John Roe"},
        "creator_user_id": "11111111-2222-3333-4444-555555555555",
    }
    record.update(personal)
    record["resources"][0]["author"] = "Jane Doe"
    dumped = datasets.detail(record, "en", allowed, ATTRIBUTION).model_dump_json()
    dumped += datasets.summarize(record, "en").model_dump_json()
    for value in ("Jane Doe", "jane@example.org", "John Roe", "john@example.org", "11111111"):
        assert value not in dumped


def test_facet_items_are_sorted_by_use_and_named_for_people(read):
    result = json.loads(read("facets.json"))["result"]
    organizations = datasets.facet_items(result, "organization")
    assert len(organizations) == 53
    assert organizations[0].model_dump() == {
        "name": "dsk",
        "title": "Azərbaycan Respublikasının Dövlət Statistika Komitəsi",
        "datasets": 1662,
    }
    counts = [(-item.datasets, item.name) for item in organizations]
    assert counts == sorted(counts)
    licenses = {item.name: item for item in datasets.facet_items(result, "license_id")}
    assert licenses["cc-zero"].datasets == 1747
    assert licenses["notspecified"].datasets > 0
    assert len(datasets.facet_items(result, "groups")) == 12


def test_a_missing_facet_is_an_empty_list():
    assert datasets.facet_items({}, "organization") == []
    assert datasets.facet_items({"search_facets": {"organization": {}}}, "organization") == []
