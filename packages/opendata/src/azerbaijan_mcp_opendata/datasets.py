"""Turn CKAN dataset records into the compact models the tools return.

CKAN keeps names and e-mail addresses of individuals in the `author` and `maintainer` fields.
They are never copied into a model here (see docs/data-policy.md in the repository).
"""

import re
from collections.abc import Callable
from typing import Any

from .models import (
    DatasetDetail,
    DatasetSummary,
    FacetItem,
    Group,
    License,
    Organization,
    ResourceInfo,
)

DATASET_URL = "https://opendata.az/en/dataset/{name}"
PREVIEW_FORMATS = {"CSV", "JSON", "GEOJSON"}
UNSTATED_LICENCES = {"", "notspecified"}
SUMMARY_CHARS = 300
DETAIL_CHARS = 4000


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _text(raw: dict[str, Any], field: str, lang: str) -> str:
    """The requested language, else English, else Azerbaijani, else the plain field."""
    translated = raw.get(f"{field}_translated") or {}
    for key in (lang, "en", "az"):
        value = translated.get(key)
        if value:
            return str(value)
    return str(raw.get(field) or "")


def _format(resource: dict[str, Any]) -> str:
    return (resource.get("format") or "").strip().lstrip(".").upper()


def _license(raw: dict[str, Any]) -> License:
    license_id = raw.get("license_id") or ""
    return License(
        id=license_id,
        title=raw.get("license_title") or "",
        known=license_id not in UNSTATED_LICENCES,
    )


def summarize(raw: dict[str, Any], lang: str, description_chars: int = SUMMARY_CHARS) -> DatasetSummary:
    organization = raw.get("organization")
    resources = raw.get("resources") or []
    return DatasetSummary(
        id=raw["id"],
        name=raw["name"],
        title=_text(raw, "title", lang),
        description=_clip(_text(raw, "notes", lang), description_chars),
        organization=(
            Organization(name=organization["name"], title=organization.get("title") or organization["name"])
            if organization
            else None
        ),
        groups=[
            Group(name=group["name"], title=group.get("display_name") or group.get("title") or group["name"])
            for group in raw.get("groups") or []
        ],
        license=_license(raw),
        formats=sorted({fmt for resource in resources if (fmt := _format(resource))}),
        num_resources=int(raw.get("num_resources") or len(resources)),
        modified=raw.get("metadata_modified") or "",
        url=DATASET_URL.format(name=raw["name"]),
    )


def _resource(resource: dict[str, Any], lang: str, host_allowed: Callable[[str], bool]) -> ResourceInfo:
    fmt = _format(resource)
    url = resource.get("url") or ""
    note = None
    if fmt not in PREVIEW_FORMATS:
        note = f"{fmt or 'This kind of'} files are not previewed; use the link."
    elif not host_allowed(url):
        note = "The file is hosted outside the allowed hosts; use the link."
    size = resource.get("size")
    return ResourceInfo(
        id=resource["id"],
        name=_text(resource, "name", lang),
        format=fmt,
        size_bytes=int(size) if str(size).isdigit() else None,
        url=url,
        previewable=note is None,
        preview_note=note,
    )


def detail(
    raw: dict[str, Any],
    lang: str,
    host_allowed: Callable[[str], bool],
    attribution: str,
) -> DatasetDetail:
    summary = summarize(raw, lang, DETAIL_CHARS)
    notes = []
    if not summary.license.known:
        notes.append("No licence is stated for this dataset. Ask the publisher before reusing it.")
    return DatasetDetail(
        **summary.model_dump(),
        tags=[tag["name"] for tag in raw.get("tags") or []],
        created=raw.get("metadata_created") or "",
        resources=[_resource(item, lang, host_allowed) for item in raw.get("resources") or []],
        source=summary.url,
        attribution=attribution,
        notes=notes,
    )


def facet_items(result: dict[str, Any], field: str) -> list[FacetItem]:
    """Facet values with their display names, most used first."""
    items = ((result.get("search_facets") or {}).get(field) or {}).get("items") or []
    found = [
        FacetItem(
            name=item["name"],
            title=item.get("display_name") or item["name"],
            datasets=int(item.get("count") or 0),
        )
        for item in items
    ]
    return sorted(found, key=lambda item: (-item.datasets, item.name))
