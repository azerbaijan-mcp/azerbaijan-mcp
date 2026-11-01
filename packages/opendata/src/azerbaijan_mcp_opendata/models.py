"""Tool output models."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class Organization(BaseModel):
    name: str = Field(description="Short id to use as the organization filter, for example dsk.")
    title: str = Field(description="Publisher name as the portal shows it (Azerbaijani).")


class Group(BaseModel):
    name: str = Field(description="Short id to use as the group filter, for example economics.")
    title: str


class License(BaseModel):
    id: str = Field(description="Licence id such as cc-zero or cc-by. Empty if none is stated.")
    title: str
    known: bool = Field(description="False when the publisher did not state a licence.")


class DatasetSummary(BaseModel):
    id: str
    name: str = Field(description="URL slug. Also accepted wherever a dataset id is expected.")
    title: str
    description: str
    organization: Organization | None
    groups: list[Group]
    license: License
    formats: list[str] = Field(description="File formats of the resources, for example CSV.")
    num_resources: int
    modified: str
    url: str = Field(description="The dataset's page on opendata.az.")


class ResourceInfo(BaseModel):
    id: str
    name: str
    format: str
    size_bytes: int | None
    url: str
    previewable: bool = Field(description="True when preview_resource can read the file.")
    preview_note: str | None = Field(description="Why the file cannot be previewed, if it cannot.")


class DatasetDetail(DatasetSummary):
    tags: list[str]
    created: str
    resources: list[ResourceInfo]
    source: str
    attribution: str
    notes: list[str]


class SearchResult(BaseModel):
    count: int = Field(description="Datasets matching the search, not only those returned.")
    offset: int
    limit: int
    results: list[DatasetSummary]
    source: str
    attribution: str
    notes: list[str]


class FacetItem(BaseModel):
    name: str = Field(description="Value to pass as a filter to search_datasets.")
    title: str
    datasets: int


class FacetList(BaseModel):
    items: list[FacetItem]
    source: str
    attribution: str
    notes: list[str]


class ResourcePreview(BaseModel):
    status: Literal["ok", "link_only", "unsupported_format", "too_large"]
    dataset_id: str
    resource_id: str
    resource_name: str
    format: str
    url: str = Field(description="The file's own address; open it when the preview is not enough.")
    reason: str | None = Field(default=None, description="Why there is no preview, if there is none.")
    size_bytes: int | None = None
    encoding: str | None = None
    delimiter: str | None = Field(default=None, description="CSV only.")
    rows: list[list[str]] | None = Field(
        default=None, description="CSV only: the first non-empty rows. The first row is often not a header."
    )
    total_rows: int | None = Field(default=None, description="CSV only: non-empty rows in the file.")
    blank_rows_skipped: int | None = Field(default=None, description="CSV only.")
    records: list[dict[str, Any]] | None = Field(default=None, description="JSON only.")
    total_records: int | None = Field(default=None, description="JSON only.")
    table_key: str | None = Field(default=None, description="JSON only: where the records were found.")
    meta: dict[str, Any] | None = Field(default=None, description="JSON only: the other top-level fields.")
    truncated: bool | None = Field(default=None, description="True when the file has more rows.")
    license: License
    source: str
    attribution: str
