"""Tool output models."""

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["ok", "ambiguous", "too_large"]


class Topic(BaseModel):
    id: str = Field(description="Value for the topic filter of search_tables, for example 994_002.")
    name: str
    tables: int = Field(description="Number of tables in the topic.")


class TopicList(BaseModel):
    topics: list[Topic]
    source: str
    attribution: str


class TableSummary(BaseModel):
    table_id: str = Field(
        description="Id for describe_table and get_table_data, such as DT_AA_001."
    )
    name: str
    description: str
    topic_id: str
    topic: str
    url: str = Field(description="The table's page on the Committee's site.")


class TableSearch(BaseModel):
    count: int = Field(description="Tables matching the search, not only those returned.")
    offset: int
    limit: int
    results: list[TableSummary]
    notes: list[str]
    source: str
    attribution: str


class DimensionInfo(BaseModel):
    name: str
    categories: int = Field(description="Number of categories in the dimension.")
    matching: int = Field(description="Categories that match category_query, or all without one.")
    examples: list[str] = Field(
        description="The first matching categories. A nested category reads 'parent > child'."
    )


class TableDescription(BaseModel):
    status: Status = Field(description="ok, or why get_table_data will not return rows.")
    reason: str | None = Field(description="Set when status is not ok.")
    table: TableSummary
    rows: int | None = Field(description="Rows in the whole table; null when it is too large.")
    periods: int | None
    first_period: str | None
    last_period: str | None
    period_types: list[str] = Field(description="As published: Y is yearly and M is monthly.")
    units: list[str] = Field(
        description="Units named in the rows. Many tables name theirs in the title."
    )
    dimensions: list[DimensionInfo]
    notes: list[str]
    source: str
    attribution: str


class TableData(BaseModel):
    status: Status = Field(description="ok, or why no rows are returned.")
    reason: str | None = Field(description="Set when status is not ok.")
    table_id: str
    name: str | None = Field(description="The table's title; null when the table was not read.")
    url: str = Field(description="The table's page on the Committee's site.")
    columns: list[str] = Field(
        description="What each cell of a row is: period, one column per dimension, value, and "
        "symbol and unit when the rows have them."
    )
    rows: list[list[str | int | float | None]]
    total_rows: int = Field(description="Rows matching the filters, not only those returned.")
    offset: int
    next_offset: int | None = Field(
        description="Pass as offset for the next rows; null at the end."
    )
    notes: list[str]
    source: str
    attribution: str
