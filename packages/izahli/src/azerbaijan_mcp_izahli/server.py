"""FastMCP server for the explanatory dictionary of the Azerbaijani language."""

import asyncio
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from .errors import IzahliError
from .models import Browse, Definition, EntryText, SearchResults
from .store import Store

INSTRUCTIONS = (
    "The explanatory dictionary of the Azerbaijani language (Azərbaycan dilinin izahlı lüğəti, "
    "four volumes), read from a database on this computer that the user extracted from their own "
    "copy; the server ships no dictionary text. define looks a headword up and returns its "
    "entries, search finds entries by the words in their text (a lookup by meaning), browse lists "
    "the entries around a headword in print order and read_entry reads the rest of a long entry. "
    "The dictionary lists base forms, not inflected ones: look up kitab, not kitabları. Entries "
    "are machine-extracted from PDFs and may contain errors; pages are PDF pages, not printed "
    "ones. Cite the dictionary, not this server. The first call builds a local index and takes a "
    "few seconds."
)
READ_ONLY = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}
MAX_INT = 2**31 - 1  # more than any dictionary has; keeps the numbers inside what SQLite takes
MAX_CHARS = Annotated[
    int,
    Field(ge=200, le=50000, description="Longest piece of an entry's text to return."),
]


def create_server(store: Store | None = None) -> FastMCP:
    """Build the server. Tests pass a store over a small invented database."""
    dictionary = store or Store.from_env()
    mcp = FastMCP(name="azerbaijan-mcp-izahli", instructions=INSTRUCTIONS)

    async def ask(function, *args):
        try:
            return await asyncio.to_thread(function, *args)
        except IzahliError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool(annotations=READ_ONLY)
    async def define(
        word: Annotated[
            str,
            Field(
                min_length=1,
                max_length=100,
                description="A headword, as printed or typed: kitab, İŞIQ, ÇAY², AB(B)ASI. Case "
                "and accents may be left out.",
            ),
        ],
        max_chars: MAX_CHARS = 3000,
    ) -> Definition:
        """Look a word up: its entries in the dictionary, in print order, with their meanings.

        Homonyms are separate entries (ÇAY¹, ÇAY²). A headword may be typed as printed, with its
        optional letters (AB(B)ASI) or its number, and a variant is found under each spelling. If
        no headword is spelled as given, accents and hyphens are ignored (seher finds şəhər and
        səhər). An entry that only says `bax X` (see X) comes with X's entry in `followed`. The
        word must be a headword, not an inflected form: for kitabları look up kitab. When nothing
        matches, `suggestions` lists headwords to try. Long entries are cut at max_chars:
        read_entry gives the rest.
        """
        return await ask(dictionary.define, word, max_chars)

    @mcp.tool(annotations=READ_ONLY)
    async def search(
        query: Annotated[
            str,
            Field(
                min_length=1,
                max_length=200,
                description="Words to find in the entries' text, all of them: su qabı.",
            ),
        ],
        exact: Annotated[
            bool,
            Field(description="Match whole words only, not their first five letters."),
        ] = False,
        limit: Annotated[int, Field(ge=1, le=50, description="Entries to return.")] = 10,
        offset: Annotated[
            int, Field(ge=0, le=MAX_INT, description="Entries to skip, for paging.")
        ] = 0,
    ) -> SearchResults:
        """Find entries whose text contains all the words: look a word up by what it means.

        Every word is required; there are no operators such as OR, and at most twelve words are
        used. Azerbaijani adds endings, so a word of four letters or more is matched by its first
        five letters (içmək finds içir and içən); exact=true matches whole words. Case does not
        matter and İ and I are told apart. Accents must be right here, unlike in define. The
        headword the query spells comes first, then headwords that contain its words, then the
        best matches. Use define to look up a headword.
        """
        return await ask(dictionary.search, query, limit, offset, exact)

    @mcp.tool(annotations=READ_ONLY)
    async def browse(
        word: Annotated[
            str | None,
            Field(
                description="A headword to start from, or the beginning of one. Leave out when "
                "giving entry_id."
            ),
        ] = None,
        entry_id: Annotated[
            int | None,
            Field(
                ge=1,
                le=MAX_INT,
                description="An entry id to start from, from any answer, to turn pages.",
            ),
        ] = None,
        before: Annotated[int, Field(ge=0, le=50, description="Entries to show before it.")] = 3,
        after: Annotated[int, Field(ge=0, le=50, description="Entries to show after it.")] = 7,
    ) -> Browse:
        """List the entries around a headword in print order, like turning the pages.

        Start from a word, or from the beginning of one (the list starts at the first headword
        that begins with it), or from an entry id. `next_id` and `previous_id` go on from either
        end: pass them as entry_id.
        """
        return await ask(dictionary.browse, word, entry_id, before, after)

    @mcp.tool(annotations=READ_ONLY)
    async def read_entry(
        entry_id: Annotated[
            int, Field(ge=1, le=MAX_INT, description="An entry id from any answer.")
        ],
        offset: Annotated[
            int,
            Field(
                ge=0,
                le=MAX_INT,
                description="Character to start at; next_offset of an answer reads on.",
            ),
        ] = 0,
        max_chars: MAX_CHARS = 6000,
    ) -> EntryText:
        """Read an entry from a character offset: the rest of one that define or search cut short.

        A few entries run to tens of thousands of characters. `next_offset` is null at the end.
        """
        return await ask(dictionary.read_entry, entry_id, offset, max_chars)

    return mcp


mcp = create_server()


def main() -> None:
    """Console entry point: serve over stdio."""
    mcp.run(show_banner=False)
