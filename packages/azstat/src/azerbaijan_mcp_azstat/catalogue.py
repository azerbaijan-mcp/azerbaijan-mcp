"""The Committee's table catalogue: parse it, group it by topic and search it."""

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .errors import UnexpectedShape

# The catalogue names every topic except the first, the one with the population tables.
FALLBACK_TOPICS = {"994_001": {"en": "Demographic indicators", "az": "Demoqrafik göstəricilər"}}
FOLD = str.maketrans({"ı": "i", "ə": "e"})


def fold(text: str) -> str:
    """Lower-case and strip accents, so that "gelir" finds "gəlir" and "Sirket" finds "Şirkət"."""
    decomposed = unicodedata.normalize("NFKD", text.casefold().translate(FOLD))
    return "".join(char for char in decomposed if not unicodedata.combining(char))


@dataclass(frozen=True, slots=True)
class Entry:
    table_id: str
    name: str
    description: str
    topic_id: str
    topic: str
    name_key: str = field(repr=False, compare=False)
    description_key: str = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class TopicCount:
    id: str
    name: str
    tables: int


def parse_catalogue(body: dict[str, Any], lang: str) -> tuple[Entry, ...]:
    rows = body.get("data")
    if not isinstance(rows, list):
        raise UnexpectedShape("The table catalogue has no 'data' list.")
    entries = []
    for raw in rows:
        try:
            table_id, name = str(raw["table_id"]), str(raw["table_name"])
        except (KeyError, TypeError) as exc:
            raise UnexpectedShape(f"A catalogue entry lacks {exc}.") from exc
        topic_id = str(raw.get("section_id") or "")
        topic = raw.get("section_name") or FALLBACK_TOPICS.get(topic_id, {}).get(lang) or topic_id
        description = re.sub(r"\s+", " ", raw.get("description") or "").strip()
        entries.append(
            Entry(
                table_id=table_id,
                name=name,
                description=description,
                topic_id=topic_id,
                topic=str(topic),
                name_key=fold(name),
                description_key=fold(description),
            )
        )
    return tuple(entries)


def topics(entries: tuple[Entry, ...]) -> list[TopicCount]:
    names: dict[str, str] = {}
    counts: Counter[str] = Counter()
    for entry in entries:
        names.setdefault(entry.topic_id, entry.topic)
        counts[entry.topic_id] += 1
    return [TopicCount(topic_id, names[topic_id], counts[topic_id]) for topic_id in sorted(counts)]


def resolve_topics(entries: tuple[Entry, ...], topic: str) -> set[str]:
    """Topic ids whose id equals, or whose name contains, the text given."""
    wanted = fold(topic).strip()
    return {
        entry.topic_id
        for entry in entries
        if wanted and (wanted == fold(entry.topic_id) or wanted in fold(entry.topic))
    }


def _score(entry: Entry, tokens: list[str], phrase: str) -> int | None:
    """Every word must appear; a word in the title counts more than one in the description."""
    total = 0
    for token in tokens:
        if token in entry.name_key:
            total += 3
        elif token in entry.description_key:
            total += 1
        else:
            return None
    if phrase and phrase in entry.name_key:
        total += 5
    return total


def search(
    entries: tuple[Entry, ...], query: str, topic_ids: set[str] | None = None
) -> list[Entry]:
    """Entries matching every word of the query, best first; no query lists the topic."""
    tokens = fold(query).split()
    phrase = " ".join(tokens)
    scored = []
    for entry in entries:
        if topic_ids is not None and entry.topic_id not in topic_ids:
            continue
        score = _score(entry, tokens, phrase)
        if score is not None:
            scored.append((score, entry))
    scored.sort(key=lambda pair: (-pair[0], pair[1].table_id))
    return [entry for _, entry in scored]
