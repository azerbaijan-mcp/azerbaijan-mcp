<!-- mcp-name: io.github.azerbaijan-mcp/dict -->

# azerbaijan-mcp-dict

**Local-only** MCP server for the explanatory dictionary of the Azerbaijani language, *Azərbaycan dilinin
izahlı lüğəti* (four volumes, about 45,000 entries). It looks words up, finds entries by what they say and
walks the dictionary in print order, with the volume, page and column of every entry.

On first use the server downloads the dictionary's database once, 5.6 MB, from this project's release page and
keeps it in your cache folder with a search index built from it. The dictionary is a copyrighted print work
and the project has no licence for it: read *Data source and terms* below. Set `DICT_DB` to use a database
of your own instead. The server runs on your computer and is never offered as a hosted service.

## Tools

| Tool | What it does |
|---|---|
| `define(word, max_chars?)` | The entries of a headword, in print order, with their meanings, etymology note (`origin`), place in the volumes and the headwords their `bax` pointers lead to. Homonyms are separate entries (`ÇAY¹`, `ÇAY²`). Entries are cut at `max_chars` (3,000 by default, up to 50,000). A miss lists headwords to try. |
| `search(query, exact?, limit?, offset?)` | The entries whose text has all the words, the headword the query spells first. Use it to find a word by its meaning (`su qabı`). `limit` is 1-50 (default 10) and `next_offset` pages on. |
| `browse(word?, entry_id?, before?, after?)` | The entries around a headword in print order, like turning the pages: `before` and `after` are 0-50 (3 and 7 by default). `next_id` and `previous_id` go on from either end. |
| `read_entry(entry_id, offset?, max_chars?)` | An entry from a character offset, to read what `define` or `search` cut short. A few entries run to tens of thousands of characters. |

A typical question, "what is the word for a vessel for water?", takes `search("su qabı")`, then
`define` of the headword it finds. "What comes after *kitab* in the dictionary?" is `browse("kitab")`.

Things worth knowing:

- **Base forms.** The dictionary lists headwords, not inflected forms: look up `kitab`, not `kitabları`.
  `define` then answers `match: none` with `suggestions` (the stem, headwords that begin with the word,
  near misses) and a note.
- **What `define` forgives.** A headword typed as printed (`AB(B)ASI`, `ÇAY²`, `AB-HAVA, ABÜHAVA`) or
  with the number a pointer gives it (`çay2`); other dashes, curly quotes and invisible characters. Case:
  `I` and `İ` are different letters and are lower-cased as Azerbaijani does. Accents and hyphens, when no
  headword is spelled as given: `seher` finds `şəhər` and `səhər` (`match: accent_free`); a space stands
  for a hyphen (`ata baba`). A variant is found under each spelling: `AB(B)ASI` as `abası` and `abbası`,
  `AB-HAVA,ABÜHAVA` as two words. An exact spelling wins over the same word without accents (`el` and `əl`
  are different words).
- **`bax` pointers.** An entry that only says `bax X` (see X) comes with X's entry in `followed`, two steps
  at most. Other pointers inside an entry are listed in `see`, with the entries they lead to. A pointer to
  a numbered sense (`bax dərd 3-cü mənada`) leads to the headword: read its text for the sense.
- **Searching.** All words must be in the entry; there are no operators such as `OR`, and at most twelve
  words are used. Azerbaijani adds endings, so a word of four letters or more is matched by its first five
  letters (`içmək` finds `içir` and `içən`); `exact=true` matches whole words. Accents must be right here,
  unlike in `define`.
- **Citations.** Every entry has `volume`, `pdf_page` and `column`. The page is the page of the volume's
  PDF, which can differ from the printed page number.
- **The text is a machine extraction** of the PDF text layer and may contain errors. Lines are joined; a
  hyphen at the end of a line is dropped unless the dictionary spells the compound with a hyphen more often
  than without (`ata-baba`), or the word is a doubled one (`aşkar-aşkar`), a number with its ending
  (`1931-ci`) or starts with `qeyri-`; a compound that occurs only once, broken at its hyphen, loses the
  hyphen. The letter-spaced italic `b a x` of the PDF is read as `bax`. Cite the printed dictionary, not
  this server.
- **Etymology.** `origin` is the note in square brackets after the part of speech (`ər.`, `fars.`, `fr.`,
  `əsli lat.`); about 11,000 entries have one.
- **The first call** downloads the database and builds the index, which takes a few seconds: about 10
  seconds and 30 MB of index for the whole dictionary. Both are kept in the cache folder
  (`%LOCALAPPDATA%\azerbaijan-mcp\dict` on Windows, `~/Library/Caches/azerbaijan-mcp/dict` on macOS,
  `~/.cache/azerbaijan-mcp/dict` elsewhere) and reused until the database file changes. Each database gets
  its own index file, so several can share the folder. A database you name is opened read-only and never
  written. The cache can be deleted at any time: the next call fetches and builds again. A file cut
  short, because the process was killed while it was being copied into place, is noticed and fetched
  or built again.
- **Not covered:** inflected forms (no morphology), and the dictionary's other editions and sibling
  dictionaries.

## Install

Add to your MCP client configuration (requires [uv](https://docs.astral.sh/uv/)):

```json
{
  "mcpServers": {
    "dict": {
      "command": "uvx",
      "args": ["azerbaijan-mcp-dict"]
    }
  }
}
```

In Claude Code: `claude mcp add dict -- uvx azerbaijan-mcp-dict`.

Three optional settings go in the client's `env`:

| Variable | Default | Meaning |
|---|---|---|
| `DICT_DB` | none | Path of a dictionary database of your own. The published one is then not downloaded. |
| `DICT_DATA_URL` | the release page of this repository | A mirror of the published database, https only (http for this computer). Its SHA-256 is still checked. |
| `DICT_CACHE_DIR` | the cache folder above | Where the database and the index are kept. A folder where the system refuses renames works too, for example `%LOCALAPPDATA%` for a server the Claude desktop app starts on Windows (`WinError 17`): the files are copied into place instead. |

## The database

The published database is the file `dict-1.sqlite.gz` of the release `dict-data-1`: 45,353
entries, 5,657,352 bytes, SHA-256 `44515ffca32d7cefc9f659bbe1ecefa82dc6908f17b5d434daffd1f921162022`, which
the package pins, so a file that differs is never used. `python -m azerbaijan_mcp_dict.asset source.sqlite
out.sqlite.gz` packs a database that way and prints the numbers to pin.

A database of your own needs one table, `entries`, and the server reads only the columns below. A
`metadata` table is optional.

```sql
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,        -- print order
    volume INTEGER NOT NULL,       -- 1 to 4
    headword TEXT NOT NULL,        -- as printed: ÇAY, AB(B)ASI, AB-HAVA,ABÜHAVA
    homonym_index INTEGER,         -- 1, 2, ... for homonyms, else NULL
    entry_text TEXT NOT NULL,      -- what follows the headword, lines as the PDF breaks them
    start_page INTEGER NOT NULL,   -- PDF page of the volume the entry starts on
    end_page INTEGER NOT NULL,
    start_column INTEGER NOT NULL  -- 1 or 2
);
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

`metadata` keys that are used: `database_title`, which names the source in every answer, and `entry_count`,
which is checked against the table so that a truncated file is refused. Other columns and tables are
ignored. The database the published one was made from has a full-text index of its own; the server does not
use it, because it misses every word that starts a sentence with a capital İ (`iki` finds 1,324 of the
1,656 entries that have it). A script that rebuilds the database from the PDFs is tracked in MCP-31.

## Data source and terms

The only request the server makes is the one download of the database, from github.com, once for each cache
folder. Answers to the checklist in the repository's [data policy](../../docs/data-policy.md), read on
2026-11-03:

- **Publisher:** bibliographies list the dictionary as published by Şərq-Qərb, Baku, 2006 (compiled by
  Ə. Orucov and others, edited by A. Axundov). No official online edition was found; azleks.az offers an
  electronic version behind a registration whose terms are unclear, and unofficial scans circulate.
- **Terms and licence:** none found, so the text is treated as all rights reserved. The project's owner
  decided on 2026-11-03 to publish the extracted database as a release asset of this repository all the
  same, without asking the publisher. That departs from the data policy's rule that terms win and carries
  the risk of a complaint. The text is in that release asset only, never in the package, the repository or
  the tests. If the publisher, the authors or their heirs object, the asset is deleted promptly.
- **robots.txt, rate limit and cache:** not applicable to a release file. The download sends the
  User-Agent `azerbaijan-mcp-dict/<version> (+<repository URL>)`, makes one request, retries once for a
  network error or a server error, stops on HTTP 403 and 429, refuses more than 100 MB and uses nothing
  whose SHA-256 differs from the pinned one. It is kept for good in the cache folder. The tests run with
  outside network access blocked.
- **Attribution:** every answer has `source` (the database's title) and an `attribution` that says the text
  is an unofficial machine extraction, and every entry has its volume, PDF page and column.
- **Personal data:** none. The entries quote published literature with the author's name, as the dictionary
  does; nothing about private people is returned or stored.
- **Publisher contacted:** no (MCP-32).
- **Decision:** go, local stdio only, with the database published as a release asset (MCP-34).

`tests/` builds an invented dictionary in the layout of the real one; no line of the real dictionary is in
this repository. To run the contract tests against your own database, and to check the published one:

```bash
DICT_DB=/path/to/azerbaycan_lugeti_1-4.sqlite uv run pytest -m live packages/dict
```

Unofficial project, not affiliated with or endorsed by the publisher or the institute that compiled the
dictionary.
