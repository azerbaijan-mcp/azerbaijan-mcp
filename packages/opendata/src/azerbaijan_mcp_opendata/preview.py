"""Turn the bytes of a CSV or JSON resource into a small, bounded preview."""

import csv
import io
import json
from typing import Any

MAX_CELL = 200
DELIMITERS = ",;\t|"


class PreviewError(Exception):
    """The file is not the CSV or JSON it claims to be."""


def decode(raw: bytes) -> tuple[str, str]:
    """Decode as UTF-8 (BOM allowed), then Windows-1254 (Turkish), then Latin-1."""
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("cp1254"), "cp1254"
    except UnicodeDecodeError:
        return raw.decode("latin-1"), "latin-1"


def sniff_delimiter(text: str) -> str:
    """Pick the delimiter that splits the first lines into the most consistent column count."""
    lines = [line for line in text[:20000].splitlines() if line.strip()][:30]
    best, best_score = ",", 0
    for delimiter in DELIMITERS:
        widths = [len(row) for row in csv.reader(lines, delimiter=delimiter)]
        if not widths:
            continue
        common = max(set(widths), key=widths.count)
        score = widths.count(common) * (common - 1)
        if score > best_score:
            best, best_score = delimiter, score
    return best


def _small(value: Any) -> Any:
    """Keep numbers and short text as they are; flatten and shorten anything bigger."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return text if len(text) <= MAX_CELL else text[: MAX_CELL - 1] + "…"


def preview_csv(raw: bytes, rows: int) -> dict[str, Any]:
    text, encoding = decode(raw)
    delimiter = sniff_delimiter(text)
    kept: list[list[str]] = []
    total = blank = 0
    try:
        for row in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
            if not any(cell.strip() for cell in row):
                blank += 1
                continue
            total += 1
            if len(kept) < rows:
                kept.append([_small(cell) for cell in row])
    except csv.Error as exc:
        raise PreviewError(f"The file is not readable as CSV: {exc}") from exc
    return {
        "encoding": encoding,
        "delimiter": delimiter,
        "rows": kept,
        "total_rows": total,
        "blank_rows_skipped": blank,
        "truncated": total > len(kept),
    }


def _is_table(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)


def preview_json(raw: bytes, rows: int) -> dict[str, Any]:
    text, encoding = decode(raw)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PreviewError(f"The file is not valid JSON: {exc}") from exc
    table_key: str | None = None
    meta: dict[str, Any] = {}
    if isinstance(data, dict):
        tables = {key: value for key, value in data.items() if _is_table(value)}
        if tables:
            table_key = max(tables, key=lambda key: len(tables[key]))
            records = tables[table_key]
        else:
            records = []
        meta = {key: _small(value) for key, value in data.items() if key != table_key}
    elif isinstance(data, list):
        records = data if _is_table(data) else [{"value": item} for item in data]
    else:
        records = [{"value": data}]
    return {
        "encoding": encoding,
        "table_key": table_key,
        "records": [{key: _small(value) for key, value in item.items()} for item in records[:rows]],
        "total_records": len(records),
        "meta": meta or None,
        "truncated": len(records) > rows,
    }
