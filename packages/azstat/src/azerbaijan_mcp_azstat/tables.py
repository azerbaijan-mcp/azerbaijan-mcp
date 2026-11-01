"""Turn a table's data answer into compact rows, and filter and describe them."""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .catalogue import fold
from .errors import AzstatError, UnexpectedShape

PATH_SEPARATOR = " > "


class UnknownDimension(AzstatError):
    """A filter names a dimension the table does not have, or one that is not unique."""


@dataclass(frozen=True, slots=True)
class Row:
    period: str
    period_type: str
    categories: tuple[str, ...]
    value: int | float | None
    symbol: str | None
    unit: str | None


@dataclass(frozen=True, slots=True)
class Table:
    table_id: str
    name: str
    dimensions: tuple[str, ...]
    rows: tuple[Row, ...]
    duplicates: int

    @property
    def ambiguous(self) -> bool:
        """Some rows share a period and categories with another row and nothing sets them apart."""
        return self.duplicates > 0


@dataclass(frozen=True, slots=True)
class DimensionSummary:
    name: str
    categories: int
    matching: int
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Overview:
    rows: int
    periods: int
    first_period: str | None
    last_period: str | None
    period_types: tuple[str, ...]
    units: tuple[str, ...]
    dimensions: tuple[DimensionSummary, ...]


def _label(record: dict[str, Any], index: int) -> str:
    """The category's name, with its parents in front when the category is nested."""
    depth = record.get(f"hierarchy_{index}_depth") or 1
    path = [record.get(f"hierarchy_{index}_level_{level}") for level in range(1, int(depth) + 1)]
    path = [str(step) for step in path if step]
    if len(path) > 1:
        return PATH_SEPARATOR.join(path)
    return str(record.get(f"level_{index}_name") or (path[0] if path else ""))


def _value(record: dict[str, Any]) -> int | float | None:
    value = record["value"]
    if value is None or (isinstance(value, int | float) and not isinstance(value, bool)):
        return value
    raise UnexpectedShape(f"A value is neither a number nor null: {value!r}.")


def parse_table(body: dict[str, Any]) -> Table:
    meta, records = body.get("table"), body.get("data")
    if not isinstance(meta, dict) or not isinstance(records, list):
        raise UnexpectedShape("The table answer has no 'table' object or 'data' list.")
    names: dict[int, str] = {}
    keys: Counter[tuple[Any, ...]] = Counter()
    rows = []
    width = None
    for record in records:
        try:
            period, value = str(record["period"]), _value(record)
        except (KeyError, TypeError) as exc:
            raise UnexpectedShape(f"A data row lacks {exc}.") from exc
        labels, ids = [], []
        index = 1
        while f"dimension_{index}" in record:
            names.setdefault(index, str(record[f"dimension_{index}"] or f"Dimension {index}"))
            labels.append(_label(record, index))
            ids.append(str(record.get(f"level_{index}_id") or labels[-1]))
            index += 1
        if width not in (None, len(labels)):
            raise UnexpectedShape("The rows of the table have different numbers of dimensions.")
        width = len(labels)
        row = Row(
            period=period,
            period_type=str(record.get("period_type") or ""),
            categories=tuple(labels),
            value=value,
            symbol=record.get("symbol") or None,
            unit=record.get("unit") or None,
        )
        keys[(row.period, row.period_type, tuple(ids), row.unit)] += 1
        rows.append(row)
    try:
        table_id, name = str(meta["table_id"]), str(meta["table_name"])
    except KeyError as exc:
        raise UnexpectedShape(f"The table answer lacks {exc}.") from exc
    return Table(
        table_id=table_id,
        name=name,
        dimensions=tuple(names[index] for index in sorted(names)),
        rows=tuple(rows),
        duplicates=sum(count for count in keys.values() if count > 1),
    )


def _bound(value: str | int | None) -> str:
    """A period limit as the rows write it: 2025-03 becomes 202503."""
    return re.sub(r"[\s\-/.]", "", str(value)) if value is not None else ""


def _dimension(table: Table, key: str) -> int:
    folded = fold(str(key)).strip()
    names = [fold(name) for name in table.dimensions]
    if folded.isdigit() and 1 <= int(folded) <= len(names):
        return int(folded) - 1
    exact = [i for i, name in enumerate(names) if name == folded]
    partial = [i for i, name in enumerate(names) if folded and folded in name]
    if len(exact) == 1:
        return exact[0]
    if len(partial) == 1 and not exact:
        return partial[0]
    listing = "; ".join(f"{i + 1}. {name}" for i, name in enumerate(table.dimensions)) or "none"
    raise UnknownDimension(
        f"{key!r} does not name exactly one dimension of this table. Dimensions: {listing}."
    )


def _matching(labels: list[str], words: str) -> set[str]:
    wanted = fold(words).split()
    return {label for label in labels if all(word in fold(label) for word in wanted)}


def select(
    table: Table,
    *,
    period_from: str | int | None = None,
    period_to: str | int | None = None,
    where: dict[str, str | int | float] | None = None,
) -> tuple[Row, ...]:
    """Rows in the period range whose categories contain the words given for each dimension."""
    first, last = _bound(period_from), _bound(period_to)
    checks = []
    for key, words in (where or {}).items():
        index = _dimension(table, key)
        distinct = list(dict.fromkeys(row.categories[index] for row in table.rows))
        checks.append((index, _matching(distinct, str(words))))
    return tuple(
        row
        for row in table.rows
        if (not first or row.period[: len(first)] >= first)
        and (not last or row.period[: len(last)] <= last)
        and all(row.categories[index] in labels for index, labels in checks)
    )


def overview(table: Table, category_query: str | None = None, examples: int = 25) -> Overview:
    periods = sorted({row.period for row in table.rows})
    dimensions = []
    for index, name in enumerate(table.dimensions):
        distinct = list(dict.fromkeys(row.categories[index] for row in table.rows))
        found = distinct
        if category_query and category_query.strip():
            matched = _matching(distinct, category_query)
            found = [label for label in distinct if label in matched]
        dimensions.append(
            DimensionSummary(name, len(distinct), len(found), tuple(found[:examples]))
        )
    return Overview(
        rows=len(table.rows),
        periods=len(periods),
        first_period=periods[0] if periods else None,
        last_period=periods[-1] if periods else None,
        period_types=tuple(sorted({row.period_type for row in table.rows if row.period_type})),
        units=tuple(sorted({row.unit for row in table.rows if row.unit})),
        dimensions=tuple(dimensions),
    )
