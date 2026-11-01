<!-- mcp-name: io.github.azerbaijan-mcp/azstat -->

# azerbaijan-mcp-azstat

MCP server for the **State Statistical Committee of Azerbaijan** ([azstat.gov.az](https://www.azstat.gov.az)).
It searches the Committee's statistical tables (about 1,800 in 31 topics: population, labour market,
education, prices, trade and more) and reads their data through the Committee's open data API: no API
key, no scraping.

## Tools

| Tool | What it does |
|---|---|
| `list_topics(lang?)` | The 31 topics with their table counts. |
| `search_tables(query?, topic?, limit?, offset?, lang?)` | Searches table titles and descriptions. Every word must appear and title matches rank first. Without a query it lists the tables of a topic. |
| `describe_table(table_id, category_query?, lang?)` | What a table holds: description, periods, units and each dimension's categories. `category_query` finds the exact category names. |
| `get_table_data(table_id, period_from?, period_to?, where?, limit?, offset?, lang?)` | Rows in long format. `where` filters categories, for example `{"Indicator": "Total population"}`. `limit` is 1-500 (default 50) and `next_offset` pages on. |

A typical question, "what was the population of Azerbaijan in 2023?", takes `search_tables("population")`,
then `describe_table("DT_AA_001")`, then
`get_table_data("DT_AA_001", period_from=2023, where={"Indicator": "Total population"})`.

Things worth knowing:

- `lang` is `en` or `az`; the API offers no other. Titles, categories and the words searched are in that
  language. Accents are ignored, so `gelir` finds `gəlir`.
- Data is in long format, one row per period and category combination. `columns` names the cells:
  `period`, one column per dimension, `value`, and `symbol` and `unit` when rows have them. Periods are
  written `2023` for years and `202603` for months. A nested category reads `parent > child`.
- A `null` value with a `symbol` (seen: `-` and `...`) means the Committee published the symbol instead
  of a number. The symbol is returned as published, not interpreted. Many tables give their unit only
  in the title.
- The API has no filters, so a table is read whole and cut here. At most 20 MB per table is read (a
  larger one returns `status` `too_large`), and it is cached for 30 minutes. The largest table in the
  sample checked was 9 MB.
- Some tables seem to leave out a dimension. In a sample of 26 tables, 2 had several values for the
  same period and categories with nothing to tell them apart. For those, `get_table_data` returns
  `status` `ambiguous`, no rows and the link to the table on the Committee's site; `describe_table`
  still shows what they hold.

## Install

Add to your MCP client configuration (requires [uv](https://docs.astral.sh/uv/)):

```json
{
  "mcpServers": {
    "azstat": {
      "command": "uvx",
      "args": ["azerbaijan-mcp-azstat"]
    }
  }
}
```

In Claude Code: `claude mcp add azstat -- uvx azerbaijan-mcp-azstat`.

One optional setting goes in the client's `env`:

| Variable | Default | Meaning |
|---|---|---|
| `AZSTAT_API_BASE` | `https://www.azstat.gov.az/AsisOpenDataApi` | API base URL, https only. |

## Data source and terms

The data is published by the State Statistical Committee at <https://www.azstat.gov.az>. This server
reads its open data API, the `tables` and `data` actions of `AsisOpenDataApi`. The API has no public
documentation (no documentation page answers at the usual paths), so a live contract test pins the
shape of its answers. Answers to the checklist in the repository's
[data policy](../../docs/data-policy.md), read on 2026-11-01:

- **Terms:** the Committee's own pages state no terms for the API and ask users to cite the source. The
  national open data portal, opendata.az, lists `AsisOpenDataApi` addresses among the files of 1,426 of
  the Committee's 1,662 datasets there, and all 1,662 carry the CC0 licence. Its FAQ
  (<https://opendata.az/page/faq>, updated 8 April 2025) defines open data as data anyone can access,
  use and share again, and tells developers they can build applications on the data and the API.
- **robots.txt:** none is published (`www.azstat.gov.az/robots.txt` answers 404).
- **Attribution:** every response has `source` and `attribution` fields and the link to the table's
  page. Cite the Committee when you use the numbers.
- **Rate limit and cache:** the User-Agent is `azerbaijan-mcp-azstat/<version>`, with at most one
  request per second, one retry for network errors and 5xx, and a stop on 403 or 429. The table list
  is cached for an hour and each table for 30 minutes.
- **Personal data:** none. The tables are aggregate statistics.
- **Publisher contacted:** no.
- **Decision:** go, as an official, read-only API.

Unofficial project, not affiliated with or endorsed by the State Statistical Committee.

`tests/fixtures/` holds trimmed copies of real answers from the API; `DT_AA_001` and `DT_BE_119` are
whole.
