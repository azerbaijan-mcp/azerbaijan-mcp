"""What the dictionary can be asked, answered from the serving index. No MCP in here."""

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import index
from . import text as rules
from .errors import BadQuery, NotConfigured, NotFound
from .models import (
    Browse,
    Definition,
    Entry,
    EntryRef,
    EntryText,
    Followed,
    Neighbour,
    SearchHit,
    SearchResults,
    SeeAlso,
)

ATTRIBUTION = (
    "{title}, read from a database its user extracted from the PDF text layer of the volumes. "
    "This is an unofficial machine extraction and may contain errors: the printed dictionary is "
    "the authority. Pages are PDF page numbers."
)
COLUMNS = "id, volume, page, col, headword, homonym, origin, text"
MAX_ENTRIES = 12  # entries shown for one headword
MAX_FOLLOWED = 6
MAX_SEE = 8
MAX_SUGGESTIONS = 8
MIN_STEM = 3  # shorter stems (ki, ev) are guessed last: they are as likely to be a coincidence
PREVIEW = 120
# The last letter of a stem softens before an ending: çiçək, çiçəyi. Undo it to find the stem.
SOFTENED = (("y", "k"), ("ğ", "q"), ("c", "ç"), ("d", "t"))
BEYOND = "\U0010ffff"  # sorts after every character: the end of a prefix range


class Store:
    """The dictionary on this computer. The index is built on first use."""

    def __init__(self, source: Path | None, cache: Path | None = None) -> None:
        self._source = source
        self._cache = cache or index.default_cache_dir()
        self._lock = threading.Lock()
        self._index: Path | None = None
        self._title = index.DEFAULT_TITLE

    @classmethod
    def from_env(cls) -> "Store":
        path = os.environ.get("IZAHLI_DB", "").strip()
        return cls(Path(path).expanduser() if path else None)

    # -- plumbing

    def _ready(self) -> Path:
        with self._lock:
            if self._index is None or not self._index.is_file():  # or the cache was deleted
                if self._source is None:
                    raise NotConfigured(
                        "No dictionary database is set. Point IZAHLI_DB at the SQLite file of the "
                        "dictionary; the README lists the tables it needs."
                    )
                path = index.ensure(self._source, self._cache)
                self._title = index.title(path)
                self._index = path
            return self._index

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = index.connect(self._ready())
        db.row_factory = sqlite3.Row
        try:
            yield db
        finally:
            db.close()

    def _credit(self) -> dict[str, str]:
        return {"source": self._title, "attribution": ATTRIBUTION.format(title=self._title)}

    @staticmethod
    def _rows(db: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
        marks = ",".join("?" * len(ids))
        sql = f"SELECT {COLUMNS} FROM entry WHERE id IN ({marks}) ORDER BY id"
        return db.execute(sql, ids).fetchall()

    @staticmethod
    def _lookup(db: sqlite3.Connection, forms: list[str]) -> tuple[list[int], str]:
        """The ids of the entries a word names: spelled so, else ignoring accents and hyphens.

        A space may stand for a hyphen (ata baba).
        """
        spellings = list(dict.fromkeys(s for form in forms for s in (form, form.replace(" ", "-"))))
        for column, probes, match in (
            ("form", spellings, "exact"),
            ("plain", [rules.accent_free(spelling) for spelling in spellings], "accent_free"),
        ):
            marks = ",".join("?" * len(probes))
            sql = f"SELECT DISTINCT entry_id FROM form WHERE {column} IN ({marks}) ORDER BY 1"
            if rows := db.execute(sql, probes).fetchall():
                return [row[0] for row in rows], match
        return [], "none"

    @staticmethod
    def _resolve(db: sqlite3.Connection, pointer: rules.Pointer) -> list[EntryRef]:
        """The entries a "bax" pointer names, if the dictionary has that headword."""
        rows: list[sqlite3.Row] = []
        for form in pointer.forms:
            rows = db.execute(
                "SELECT DISTINCT e.id, e.headword, e.homonym FROM form f "
                "JOIN entry e ON e.id = f.entry_id WHERE f.form = ? ORDER BY e.id",
                (form,),
            ).fetchall()
            if rows:
                break
        if pointer.homonym is not None:
            rows = [row for row in rows if row["homonym"] == pointer.homonym] or rows
        return [EntryRef(id=row["id"], headword=row["headword"]) for row in rows[:4]]

    def _entry_data(
        self, db: sqlite3.Connection, row: sqlite3.Row, offset: int, max_chars: int
    ) -> dict:
        full = row["text"]
        piece, next_offset = rules.window(full, offset, max_chars)
        see = []
        for pointer in rules.pointers(piece)[:MAX_SEE]:
            if refs := self._resolve(db, pointer):
                see.append(SeeAlso(pointer=pointer.text, entries=refs))
        return {
            "id": row["id"],
            "headword": row["headword"],
            "origin": row["origin"],
            "text": piece,
            "total_chars": len(full),
            "offset": offset,
            "next_offset": next_offset,
            "volume": row["volume"],
            "pdf_page": row["page"],
            "column": row["col"],
            "see": see,
        }

    def _follow(
        self, db: sqlite3.Connection, rows: list[sqlite3.Row], max_chars: int
    ) -> list[Followed]:
        """The entries an entry that only says "bax X" leads to, through two pointers at most."""
        seen = {row["id"] for row in rows}
        followed: list[Followed] = []
        frontier = [row for row in rows if rules.is_redirect(row["text"])]
        for _ in range(2):
            leads = []
            for row in frontier:
                for pointer in rules.pointers(row["text"])[:3]:
                    for ref in self._resolve(db, pointer)[:3]:
                        if ref.id in seen or len(followed) >= MAX_FOLLOWED:
                            continue
                        seen.add(ref.id)
                        sql = f"SELECT {COLUMNS} FROM entry WHERE id = ?"
                        target = db.execute(sql, (ref.id,)).fetchone()
                        data = self._entry_data(db, target, 0, max_chars)
                        followed.append(Followed(**data, via=row["id"]))
                        if rules.is_redirect(target["text"]):
                            leads.append(target)
            frontier = leads
        return followed

    @staticmethod
    def _suggest(db: sqlite3.Connection, key: str) -> list[str]:
        """Headwords to try for a word that is not one: its stem, words it begins, near misses."""
        stems: list[int] = []
        short_stems: list[int] = []
        if len(key) >= 4:
            candidates: list[str] = []
            for cut in range(len(key) - 1, 1, -1):
                stem = key[:cut]
                candidates.append(stem)
                candidates.extend(stem[:-1] + new for old, new in SOFTENED if stem.endswith(old))
            marks = ",".join("?" * len(candidates))
            by_form: dict[str, int] = {}
            sql = f"SELECT form, entry_id FROM form WHERE form IN ({marks}) ORDER BY entry_id"
            for form, entry_id in db.execute(sql, candidates):
                by_form.setdefault(form, entry_id)
            for stem in candidates:
                if stem in by_form:
                    (stems if len(stem) >= MIN_STEM else short_stems).append(by_form[stem])
        sql = "SELECT entry_id FROM form WHERE form >= ? AND form < ? ORDER BY entry_id LIMIT 4"
        begins = [entry_id for (entry_id,) in db.execute(sql, (key, key + BEYOND))]
        plain = rules.accent_free(key)
        close: list[tuple[int, int]] = []
        if plain:
            limit = 2 if len(plain) > 5 else 1
            sql = "SELECT plain, entry_id FROM form WHERE plain >= ? AND plain < ?"
            for candidate, entry_id in db.execute(sql, (plain[0], plain[0] + BEYOND)):
                if (distance := rules.edit_distance(plain, candidate, limit)) is not None:
                    close.append((distance, entry_id))
        ranked: dict[int, None] = {}
        for entry_id in [*stems[:3], *begins, *(i for _, i in sorted(close)[:5]), *short_stems[:1]]:
            ranked.setdefault(entry_id)
        if not ranked:
            return []
        marks = ",".join("?" * len(ranked))
        sql = f"SELECT id, headword FROM entry WHERE id IN ({marks})"
        names = {row["id"]: row["headword"] for row in db.execute(sql, list(ranked))}
        suggestions: list[str] = []
        for entry_id in ranked:
            name = rules.strip_homonym_mark(names[entry_id])
            if name not in suggestions:
                suggestions.append(name)
        return suggestions[:MAX_SUGGESTIONS]

    @staticmethod
    def _miss(word: str, suggestions: list[str]) -> str:
        said = f"No headword matches {word.strip()!r}."
        return said + (f" Did you mean: {', '.join(suggestions)}?" if suggestions else "")

    # -- what can be asked

    def define(self, word: str, max_chars: int) -> Definition:
        """The entries of a headword, with what their "bax" pointers lead to."""
        forms = rules.query_forms(word)
        if not forms:
            raise BadQuery("Give the word to look up.")
        key = forms[0]
        with self._db() as db:
            ids, match = self._lookup(db, forms)
            if not ids:
                suggestions = self._suggest(db, key)
                notes = [self._miss(word, [])]
                if " " in key:
                    notes.append(
                        "Headwords are single words; to look for a phrase or a meaning, use search."
                    )
                elif suggestions:
                    notes.append(
                        "The dictionary lists base forms, not inflected ones: try the stem "
                        "(kitab, not kitabları)."
                    )
                return Definition(
                    query=word,
                    match="none",
                    entries=[],
                    followed=[],
                    suggestions=suggestions,
                    notes=notes,
                    **self._credit(),
                )
            notes = []
            if match == "accent_free":
                notes.append(
                    f"No headword is spelled {word.strip()!r}; these match once accents and "
                    "hyphens are ignored."
                )
            if len(ids) > MAX_ENTRIES:
                notes.append(f"{len(ids)} entries match; the first {MAX_ENTRIES} are shown.")
            rows = self._rows(db, ids[:MAX_ENTRIES])
            entries = [Entry(**self._entry_data(db, row, 0, max_chars)) for row in rows]
            followed = self._follow(db, rows, max_chars)
            if any(entry.next_offset is not None for entry in [*entries, *followed]):
                notes.append("Some entries are cut short: read_entry gives the rest.")
            return Definition(
                query=word,
                match=match,
                entries=entries,
                followed=followed,
                suggestions=[],
                notes=notes,
                **self._credit(),
            )

    def read_entry(self, entry_id: int, offset: int, max_chars: int) -> EntryText:
        with self._db() as db:
            row = db.execute(f"SELECT {COLUMNS} FROM entry WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                raise NotFound(f"No entry has id {entry_id}.")
            data = self._entry_data(db, row, offset, max_chars)
        notes = []
        if offset >= (total := data["total_chars"]):
            notes.append(f"offset is past the end: the entry has {total:,} characters.")
        return EntryText(**data, notes=notes, **self._credit())

    def search(self, query: str, limit: int, offset: int, exact: bool) -> SearchResults:
        found = rules.query_words(query)
        words = found[: rules.MAX_QUERY_WORDS]
        expression, patterns = rules.match_terms(words, exact)
        if not expression:
            raise BadQuery("Give at least one word to look for.")
        # The headword the query spells comes first, then headwords that contain its words, then
        # the rest by relevance. Relevance alone would sink a long entry such as the one for a
        # common verb below short entries that merely use the word.
        sql = (
            "SELECT e.id, e.volume, e.page, e.col, e.headword, e.text FROM fts "
            "JOIN entry e ON e.id = fts.rowid WHERE fts MATCH ? "
            "ORDER BY e.id IN (SELECT entry_id FROM form WHERE form = ?) DESC, "
            "e.id IN (SELECT rowid FROM fts WHERE fts MATCH ?) DESC, "
            "bm25(fts, 6.0, 1.0), e.id LIMIT ? OFFSET ?"
        )
        arguments = (expression, "-".join(words), f"head : ({expression})", limit, offset)
        with self._db() as db:
            try:
                count = db.execute(
                    "SELECT count(*) FROM fts WHERE fts MATCH ?", (expression,)
                ).fetchone()[0]
                rows = db.execute(sql, arguments).fetchall()
            except sqlite3.OperationalError as exc:
                raise BadQuery(f"The search could not be run: {exc}") from exc
        end = offset + len(rows)
        notes = []
        if len(found) > len(words):
            notes.append(f"Only the first {len(words)} words were used.")
        if not count:
            note = (
                "Nothing matched. Try fewer or other words; words of four letters or more already "
                "match by their first five letters."
            )
            if "I" in query:
                note += " I and İ are different letters: İki is not Iki."
            notes.append(note)
        return SearchResults(
            query=query,
            count=count,
            offset=offset,
            limit=limit,
            next_offset=end if end < count else None,
            results=[
                SearchHit(
                    id=row["id"],
                    headword=row["headword"],
                    snippet=rules.snippet(row["text"], patterns),
                    volume=row["volume"],
                    pdf_page=row["page"],
                    column=row["col"],
                )
                for row in rows
            ],
            notes=notes,
            **self._credit(),
        )

    def browse(self, word: str | None, entry_id: int | None, before: int, after: int) -> Browse:
        if (word is None) == (entry_id is None):
            raise BadQuery("Give a word or an entry_id: one of them, not both.")
        notes: list[str] = []
        with self._db() as db:
            if entry_id is not None:
                if db.execute("SELECT 1 FROM entry WHERE id = ?", (entry_id,)).fetchone() is None:
                    raise NotFound(f"No entry has id {entry_id}.")
                anchor = entry_id
            else:
                forms = rules.query_forms(word or "")
                if not forms:
                    raise BadQuery("Give the word to start from.")
                key = forms[0]
                ids, match = self._lookup(db, forms)
                if ids:
                    anchor = ids[0]
                    if match == "accent_free":
                        notes.append(f"No headword is spelled {word!r}; started at the closest.")
                else:
                    sql = "SELECT min(entry_id) FROM form WHERE form >= ? AND form < ?"
                    (anchor,) = db.execute(sql, (key, key + BEYOND)).fetchone()
                    if anchor is None:
                        raise NotFound(self._miss(word or "", self._suggest(db, key)))
                    notes.append(
                        f"No headword {word!r}; the list starts at the first that begins with it."
                    )
            earlier = db.execute(
                f"SELECT {COLUMNS} FROM entry WHERE id < ? ORDER BY id DESC LIMIT ?",
                (anchor, before),
            ).fetchall()
            later = db.execute(
                f"SELECT {COLUMNS} FROM entry WHERE id >= ? ORDER BY id LIMIT ?",
                (anchor, after + 1),
            ).fetchall()
            rows = [*reversed(earlier), *later]
            previous_id = db.execute(
                "SELECT max(id) FROM entry WHERE id < ?", (rows[0]["id"],)
            ).fetchone()[0]
            next_id = db.execute(
                "SELECT min(id) FROM entry WHERE id > ?", (rows[-1]["id"],)
            ).fetchone()[0]
        return Browse(
            entries=[
                Neighbour(
                    id=row["id"],
                    headword=row["headword"],
                    preview=row["text"][:PREVIEW] + ("…" if len(row["text"]) > PREVIEW else ""),
                    volume=row["volume"],
                    pdf_page=row["page"],
                    column=row["col"],
                    anchor=row["id"] == anchor,
                )
                for row in rows
            ],
            previous_id=previous_id,
            next_id=next_id,
            notes=notes,
            **self._credit(),
        )
