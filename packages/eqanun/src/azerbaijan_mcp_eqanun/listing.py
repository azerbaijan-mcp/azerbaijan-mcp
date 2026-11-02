"""Read what api.e-qanun.az answers: search results, requisites, editions and the act types."""

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any, Literal

from .acts import fold
from .errors import UnexpectedShape

Status = Literal["in_force", "repealed", "unknown"]
STATUS_IDS = {"all": 0, "in_force": 1, "repealed": 2}
DATE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
COUNT = re.compile(r"\s*\(\d+\)\s*$")
FILE_PATH = re.compile(
    r"^https://(?:e-qanun\.az/frameworks|frameworks\.e-qanun\.az)/(\d+/[A-Za-z0-9_\-]+\.html)$"
)


@dataclass(frozen=True, slots=True)
class ActSummary:
    id: int
    title: str
    type: str | None
    status: Status
    status_text: str | None
    accept_date: str | None
    effect_date: str | None
    register_code: str | None
    citation: str | None


@dataclass(frozen=True, slots=True)
class Publication:
    source: str
    details: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ActMeta:
    summary: ActSummary
    register_date: str | None
    class_codes: tuple[str, ...]
    publications: tuple[Publication, ...]
    html_url: str


@dataclass(frozen=True, slots=True)
class Version:
    id: int
    effective_date: str | None
    file: str | None


@dataclass(frozen=True, slots=True)
class TypeNode:
    id: int
    name: str
    parent_id: int | None


def iso_date(value: Any) -> str | None:
    """03.09.2026 becomes 2026-09-03; anything else, including the text "None", becomes None."""
    found = DATE.fullmatch(str(value).strip()) if value else None
    if not found:
        return None
    day, month, year = (int(part) for part in found.groups())
    try:
        return dt.date(year, month, day).isoformat()
    except ValueError:
        return None


def status_of(name: Any) -> Status:
    folded = fold(str(name or ""))
    if folded.startswith("quvvede"):
        return "in_force"
    return "repealed" if folded.startswith("legv") else "unknown"


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text if text and text != "None" else None


def _summary(item: dict[str, Any]) -> ActSummary:
    try:
        act_id, title = int(item["id"]), str(item["title"] or "")
    except (KeyError, TypeError, ValueError) as exc:
        raise UnexpectedShape(f"An act in the answer lacks {exc}.") from exc
    return ActSummary(
        id=act_id,
        title=re.sub(r"\s+", " ", title).strip(),
        type=_text(item.get("typeName")),
        status=status_of(item.get("statusName")),
        status_text=_text(item.get("statusName")),
        accept_date=iso_date(item.get("acceptDate")),
        effect_date=iso_date(item.get("effectDate")),
        register_code=_text(item.get("registerCode")),
        citation=_text(item.get("citation")),
    )


def parse_search(body: Any) -> tuple[int, list[ActSummary]]:
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise UnexpectedShape("The search answer has no 'data' list.")
    try:
        total = int(body.get("totalCount", len(rows)))
    except (TypeError, ValueError) as exc:
        raise UnexpectedShape("The search answer's totalCount is not a number.") from exc
    return total, [_summary(row) for row in rows]


def parse_framework(body: Any) -> ActMeta:
    data = body.get("data") if isinstance(body, dict) else None
    requisite = data.get("requisite") if isinstance(data, dict) else None
    if not isinstance(requisite, dict) or not data.get("htmlUrl"):
        raise UnexpectedShape("The act answer has no 'requisite' or 'htmlUrl'.")
    summary = _summary({**requisite, "id": data.get("id")})
    sources: dict[str, list[tuple[str, str]]] = {}
    for field in requisite.get("fields") or []:
        if isinstance(field, dict) and field.get("name"):
            pair = (str(field.get("fieldName") or ""), str(field.get("fieldValue") or ""))
            sources.setdefault(str(field["name"]), []).append(pair)
    codes = requisite.get("classCodes")
    return ActMeta(
        summary=summary,
        register_date=iso_date(requisite.get("registerDate")),
        class_codes=tuple(re.findall(r"\d[\d.]*\d", str(codes))) if codes else (),
        publications=tuple(Publication(name, tuple(pairs)) for name, pairs in sources.items()),
        html_url=str(data["htmlUrl"]),
    )


def parse_versions(body: Any) -> tuple[Version, ...]:
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise UnexpectedShape("The versions answer has no 'data' list.")
    try:
        return tuple(
            Version(int(row["id"]), iso_date(row.get("effectDate")), _text(row.get("htmlPath")))
            for row in rows
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise UnexpectedShape(f"A version in the answer lacks {exc}.") from exc


def parse_types(body: Any) -> tuple[TypeNode, ...]:
    rows = body.get("data") if isinstance(body, dict) else None
    if not isinstance(rows, list):
        raise UnexpectedShape("The types answer has no 'data' list.")
    try:
        return tuple(
            TypeNode(
                id=int(row["id"]),
                name=COUNT.sub("", str(row["name"])).strip(),
                parent_id=int(row["parentId"]) if row.get("parentId") is not None else None,
            )
            for row in rows
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise UnexpectedShape(f"A type in the answer lacks {exc}.") from exc


def resolve_types(nodes: tuple[TypeNode, ...], wanted: str) -> list[TypeNode]:
    """The leaf types whose name has every word given; a group stands for the types in it."""
    words = fold(wanted).split()
    if not words:
        return []
    parents = {node.parent_id for node in nodes if node.parent_id is not None}
    chosen: dict[int, TypeNode] = {}
    for node in nodes:
        if all(word in fold(node.name) for word in words):
            leaves = [n for n in nodes if n.parent_id == node.id] if node.id in parents else [node]
            chosen.update({leaf.id: leaf for leaf in leaves})
    return list(chosen.values())


def file_path(html_url: str) -> str:
    """The act file's path from the address the API gives, which must be on e-qanun.az."""
    found = FILE_PATH.fullmatch(html_url.strip())
    if not found:
        raise UnexpectedShape(f"The act's file address is not one this server reads: {html_url!r}.")
    return found.group(1)
