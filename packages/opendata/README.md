<!-- mcp-name: io.github.azerbaijan-mcp/opendata -->

# azerbaijan-mcp-opendata

MCP server for **[opendata.az](https://opendata.az)**, the open data portal of Azerbaijan. It searches
the portal's datasets and reads their CSV and JSON files through the portal's public CKAN API: no API
key, no scraping.

## Tools

| Tool | What it does |
|---|---|
| `search_datasets(query?, organization?, group?, license?, format?, limit?, offset?, lang?)` | Searches datasets. Filters combine with AND; take their values from the `list_*` tools. `limit` is 1-50 (default 10). Without a query the newest datasets come first. |
| `get_dataset(dataset_id, lang?)` | One dataset: description, publisher, licence, tags and its files with their ids, formats and sizes. `dataset_id` is the id or the URL slug. |
| `list_organizations()` | Publishers with their dataset counts, largest first. |
| `list_groups()` | Topics with their dataset counts. |
| `list_licenses()` | Licences with their dataset counts. |
| `preview_resource(dataset_id, resource_id, rows?)` | The first rows of a CSV or the first records of a JSON file. `rows` is 1-200 (default 20). |

Things worth knowing:

- Titles and descriptions are mostly Azerbaijani. `lang` (`en`, `az`, `ru`) picks a translation when the
  portal has one, then falls back to English and Azerbaijani.
- Every dataset has its own licence, mostly CC0. `license.known` is false when the publisher states
  none, and the response says so.
- Previews read CSV, JSON and GeoJSON files only, over https, from `opendata.az` and `azstat.gov.az`
  (subdomains included), up to 5 MB. For anything else the result has `status` `link_only`,
  `unsupported_format` or `too_large` and the file's own address in `url`.
- A portal CSV often starts with a title row, so the preview returns raw rows and counts the blank rows
  it skipped. Text is decoded as UTF-8, then Windows-1254, then Latin-1 (`encoding`).
- The `author` and `maintainer` fields of a dataset, which hold names and e-mail addresses, are never
  returned.

## What the portal's API does not offer

The API is served from `admin.opendata.az`; `opendata.az/api/3/action` answers 404. On 2026-11-01 it
answered `package_search` and `package_show` and refused every other CKAN action tried with HTTP 403
from nginx: `package_list`, `organization_list`, `group_list`, `tag_list`, `license_list`,
`status_show`, `resource_show`, `resource_search` and `datastore_search`. So publishers, topics and
licences come from the facets of `package_search`, and a file's address from `package_show`. The server
stops on a 403 and says so, and the live contract tests fail if a working action starts returning one.

## Install

Add to your MCP client configuration (requires [uv](https://docs.astral.sh/uv/)):

```json
{
  "mcpServers": {
    "opendata": {
      "command": "uvx",
      "args": ["azerbaijan-mcp-opendata"]
    }
  }
}
```

In Claude Code: `claude mcp add opendata -- uvx azerbaijan-mcp-opendata`.

Both settings below are optional and go in the client's `env`:

| Variable | Default | Meaning |
|---|---|---|
| `OPENDATA_AZ_API_BASE` | `https://admin.opendata.az/api/3/action` | CKAN API base URL, https only. |
| `OPENDATA_AZ_RESOURCE_HOSTS` | `opendata.az,azstat.gov.az` | Comma-separated hosts whose files may be previewed. Subdomains match; https only. |

## Data source and terms

The data is published by the IDDA Open Data Portal, <https://opendata.az>. This server reads it through
the portal's CKAN API (`package_search` and `package_show` on `admin.opendata.az`) and, for previews,
the files the datasets link to. Answers to the checklist in the repository's
[data policy](../../docs/data-policy.md), read on 2026-11-01:

- **Terms:** the portal's FAQ (<https://opendata.az/page/faq>, updated 8 April 2025) defines open data
  as data anyone can access, use and share again, and tells developers they can build applications on
  the data and the API. It sets no rules for automated access. Each dataset also carries its own
  licence, which every response includes. Most are CC0 (1,747 of 2,054 datasets on that day) and a few
  dozen state none.
- **robots.txt:** none is published. `opendata.az` redirects the path to a search page,
  `admin.opendata.az` answers 403 and `www.azstat.gov.az` answers 404.
- **Attribution:** every response has `source` and `attribution` fields naming the portal and the
  dataset's page.
- **Rate limit and cache:** the User-Agent is `azerbaijan-mcp-opendata/<version>`, with at most one
  request per second per host and one retry for network errors and 5xx. On 403 or 429 the server stops
  and says so. Searches and datasets are cached for 10 minutes, the publisher, topic and licence lists
  for an hour. Files are limited to 5 MB and to the hosts above, and every redirect is checked again.
- **Personal data:** names and e-mail addresses from the dataset records are never copied. A file
  preview shows what the publisher put in the file, at most 200 rows, and nothing is stored.
- **Publisher contacted:** no. The FAQ settles reuse. It does not say whether the API address will stay
  as it is or why other CKAN actions answer 403; if either causes trouble, ask the operator through
  the portal's contact link.
- **Decision:** go, as an official, read-only API.

Unofficial project, not affiliated with or endorsed by IDDA or any publisher on the portal.

`tests/fixtures/` holds snapshots of public responses from the portal and from azstat (names and user
ids removed) and one synthetic CSV that imitates the portal's style: a title row, semicolons, blank rows
and a multi-line header.
