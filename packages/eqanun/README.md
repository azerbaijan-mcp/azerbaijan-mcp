<!-- mcp-name: io.github.azerbaijan-mcp/eqanun -->

# azerbaijan-mcp-eqanun

**Local-only** MCP server for [e-qanun.az](https://e-qanun.az), the legal acts base of the **Ministry of
Justice of Azerbaijan**. It searches the acts (laws, codes, decrees, orders and decisions of the
President, the Cabinet, ministries and courts) and reads their text article by article, with the
amendment notes that say which later law changed each passage.

e-qanun.az has no documented API and no terms for programs, so this server is *scraping-class* under the
repository's [data policy](../../docs/data-policy.md): it runs only on your computer, from your own
connection, and is never offered as a hosted service.

## Tools

| Tool | What it does |
|---|---|
| `search_acts(query?, field?, type?, status?, exact?, limit?, offset?)` | Searches act titles, or with `field="text"` their full texts, newest adoption date first. Only acts in force unless `status` is `repealed` or `all`. `type` takes words from a kind of act's name: `qanun`, `məcəllə`, `fərman`, `sərəncam`, `Nazirlər Kabineti` or a ministry. Without `query` it lists the newest acts. `limit` is 1-50 (default 10) and `next_offset` pages on. |
| `get_act(act_id, offset?, max_chars?)` | An act's title, kind, status, dates, where it was published and the dates of its editions, and its text from `offset` (a piece of 6,000 characters by default, up to 50,000) with the amendment notes and links to other acts that belong to the piece. For an act divided into articles it gives their number and range. |
| `get_article(act_id, article, offset?, max_chars?)` | One article of a code or law: heading, text, the amendment notes in it, the acts it links to, and the numbers of the previous and next articles. `article` is `105`, `105-1`, `Maddə 105` or `105.1` (which reads article 105). |
| `find_in_act(act_id, query, limit?, offset?)` | The articles of one act that contain all the words, the most occurrences first, each with a snippet. In an act without articles the results are paragraphs, and `position` is the `offset` to give `get_act`. |

A typical question, "what does the Civil Code say about limitation periods?", takes
`search_acts("mülki", type="məcəllə")` (the Civil Code is act 46944), then
`find_in_act(46944, "iddia müddəti")`, then `get_article(46944, 373)`.

Things worth knowing:

- **Amendment notes.** The text carries `[12]`-style markers. Each is a note saying which later law added,
  changed or repealed the passage; `get_article` and `get_act` return the notes whose markers are in what
  they return. They are the site's own notes, not interpreted.
- **Links to other acts.** `references` lists the acts a text links to, with their ids for `get_act`. In
  the Civil Code, labels such as `KMQ23` mark a decision of the Constitutional Court on the passage; the
  site gives the decision's title, which is returned. A label such as `KM2` links to a note elsewhere in
  the file and is left as it stands.
- **Repealed acts** are flagged in every answer and must not be presented as current law.
- **Only the current edition** of an act is read. `edition_dates` shows the editions the site keeps;
  older ones are not read.
- **Matching** ignores case and accents, so `mehdudlasdirma` finds `məhdudlaşdırma`. A word matches as
  part of a longer one, and a final `k` or `q` of a query word is ignored, so `qanunvericilik` finds
  `qanunvericiliyi`. All words must be in the same article. Word forms are not otherwise reduced.
- **Articles** are found by their headings ("Maddə 105."). An act that does not use them, such as most
  decisions, is read as numbered paragraphs. The lists after the last article (amending laws, sources,
  annexes, the President's signature) are in the text but not in the article.
- **Size.** An act's file is read whole, kept in memory for an hour (four acts at most) and never written
  to disk. The Civil Code is 10 MB and takes a few seconds the first time. A file over 30 MB is not read:
  `get_act` then returns `status` `too_large`, the act's details and the link to read it on the site.
- **Not covered:** the Nakhchivan portal (napi.e-qanun.az) and the text of older editions.

## Install

Add to your MCP client configuration (requires [uv](https://docs.astral.sh/uv/)):

```json
{
  "mcpServers": {
    "eqanun": {
      "command": "uvx",
      "args": ["azerbaijan-mcp-eqanun"]
    }
  }
}
```

In Claude Code: `claude mcp add eqanun -- uvx azerbaijan-mcp-eqanun`.

Two optional settings go in the client's `env`:

| Variable | Default | Meaning |
|---|---|---|
| `EQANUN_API_BASE` | `https://api.e-qanun.az` | Base URL of the site's search API, https only. |
| `EQANUN_FILES_BASE` | `https://frameworks.e-qanun.az` | Base URL of the act files, https only. |

## Data source and terms

The acts are published at <https://e-qanun.az>. This server calls the site's own search API
(`getDetailSearch`, `framework/<id>`, `getVersions`, `all-type` on `api.e-qanun.az`) and reads each act's
file. The API returns the address of the file on `e-qanun.az`, which answers HTTP 403 to a program, so the
same file is read from `frameworks.e-qanun.az`, where the site serves it openly. Nothing is done to hide
what the server is. A server that was refused would stop (see below), not try another way in. Neither
the API nor the files are documented, so a live contract test pins the shape of the answers. Answers to
the checklist in the repository's [data policy](../../docs/data-policy.md), read on 2026-11-02:

- **Terms:** the site publishes no terms of use, and the API's Swagger page answers 403. The Law on
  Copyright and Related Rights (No. 115-IQ, article 7) leaves official documents, among them laws and
  decisions, outside copyright, and the site is reported free of charge. The texts are still
  unofficial copies: the State Register of Legal Acts holds the official ones.
- **robots.txt:** none is published (`e-qanun.az/robots.txt` answers 404).
- **Attribution:** every answer has `source` (the act's page on e-qanun.az), `attribution` and
  `fetched_at`, and says that the State Register of Legal Acts is the official source.
- **Rate limit and cache:** the User-Agent is `azerbaijan-mcp-eqanun/<version> (+<repository URL>)`, at
  most one request per second to each host, one retry for network errors and 5xx, and a stop on 403 or
  429. Searches are cached for 10 minutes; act details, editions, kinds of act and act files for an hour
  (a kept file is asked about with `If-None-Match`, not downloaded again).
- **Personal data:** the acts are public legal texts. A few of them (orders awarding honours or
  appointing officials, for example) name people, and are returned as published; nothing is stored.
- **Publisher contacted:** no.
- **Decision:** go, local stdio only.

This is a reading aid, not legal advice: check an act's current text and status in the State Register of
Legal Acts before relying on it. Unofficial project, not affiliated with or endorsed by the Ministry of
Justice.

`tests/fixtures/` holds trimmed copies of real answers and of two real act files (paragraphs of the Civil
Code and of a decision of the Ministry of Justice, with the notes they point to).
