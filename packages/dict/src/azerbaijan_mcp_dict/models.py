"""Tool output models."""

from typing import Literal

from pydantic import BaseModel, Field

Match = Literal["exact", "accent_free", "none"]


class EntryRef(BaseModel):
    id: int = Field(description="Entry id for read_entry and browse.")
    headword: str


class SeeAlso(BaseModel):
    pointer: str = Field(
        description="What the entry says after 'bax' (see), such as 'dərd 3-cü mənada'."
    )
    entries: list[EntryRef] = Field(description="The entries of that headword, in print order.")


class Entry(BaseModel):
    id: int = Field(description="Entry id for read_entry and browse.")
    headword: str = Field(
        description="The headword as printed; homonyms carry a superscript, such as ÇAY²."
    )
    origin: str | None = Field(
        description="The etymology note in square brackets that opens the entry, after its part "
        "of speech: 'fars.', 'ər.', 'əsli lat.'. Null when there is none."
    )
    text: str = Field(description="The entry from `offset`, its lines joined.")
    total_chars: int = Field(description="Length of the whole entry.")
    offset: int
    next_offset: int | None = Field(
        description="Pass as offset to read_entry for the rest; null when this is the end."
    )
    volume: int = Field(description="Volume of the dictionary, 1 to 4.")
    pdf_page: int = Field(
        description="Page of the volume's PDF the entry starts on, counted from 1. It can differ "
        "from the printed page number."
    )
    column: int = Field(description="Column of that page, 1 or 2.")
    see: list[SeeAlso] = Field(
        description="Headwords this part of the entry sends the reader to with 'bax', as far as "
        "they are headwords of the dictionary."
    )


class Followed(Entry):
    via: int = Field(description="Id of the entry whose 'bax' pointer led here.")


class Definition(BaseModel):
    query: str
    match: Match = Field(
        description="exact; accent_free when the entries were found by ignoring accents and "
        "hyphens; none when nothing matched."
    )
    entries: list[Entry] = Field(description="The entries of the headword, in print order.")
    followed: list[Followed] = Field(
        description="Entries the 'bax' pointers of an entry that only points elsewhere lead to."
    )
    suggestions: list[str] = Field(description="Headwords worth trying when nothing matched.")
    notes: list[str]
    source: str
    attribution: str


class EntryText(Entry):
    notes: list[str]
    source: str
    attribution: str


class SearchHit(BaseModel):
    id: int = Field(description="Entry id for read_entry and browse.")
    headword: str
    snippet: str = Field(description="A passage of the entry around the first word found.")
    volume: int
    pdf_page: int
    column: int


class SearchResults(BaseModel):
    query: str
    count: int = Field(description="Entries matching, not only those returned.")
    offset: int
    limit: int
    next_offset: int | None = Field(
        description="Pass as offset for the next results; null at the end."
    )
    results: list[SearchHit] = Field(description="Best match first.")
    notes: list[str]
    source: str
    attribution: str


class Neighbour(BaseModel):
    id: int = Field(description="Entry id for read_entry and browse.")
    headword: str
    preview: str = Field(description="The start of the entry.")
    volume: int
    pdf_page: int
    column: int
    anchor: bool = Field(description="The entry the listing was asked to start from.")


class Browse(BaseModel):
    entries: list[Neighbour] = Field(description="In print order.")
    previous_id: int | None = Field(
        description="Pass as entry_id with before to go back; null at the start."
    )
    next_id: int | None = Field(description="Pass as entry_id to go on; null at the end.")
    notes: list[str]
    source: str
    attribution: str
