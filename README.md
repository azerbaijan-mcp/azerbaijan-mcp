# azerbaijan-mcp

Open-source [MCP](https://modelcontextprotocol.io) servers for Azerbaijani data and services. One small,
independently installable server per data source.

| Server | Package | Source | Status |
|---|---|---|---|
| [cbar](packages/cbar) | `azerbaijan-mcp-cbar` | Central Bank of Azerbaijan official exchange rates (XML feed) | v0.1 |
| [opendata](packages/opendata) | `azerbaijan-mcp-opendata` | [opendata.az](https://opendata.az) open data portal (CKAN API): dataset search and CSV/JSON previews | unreleased |
| [azstat](packages/azstat) | `azerbaijan-mcp-azstat` | State Statistical Committee open data API: search about 1,800 statistical tables and read their data | v0.1 |
| [utils](packages/utils) | `azerbaijan-mcp-utils` | Offline helpers: IBAN and phone checks, amounts in manat in words, Latin and Cyrillic transliteration, official holidays and working days | unreleased |
| [eqanun](packages/eqanun) | `azerbaijan-mcp-eqanun` | [e-qanun.az](https://e-qanun.az) legal acts, local only: search acts and read articles with their amendment notes | unreleased |
| [dict](packages/dict) | `azerbaijan-mcp-dict` | Explanatory dictionary of Azerbaijani (four volumes), local only: look words up, search by meaning and browse in print order, from a database downloaded once to your computer | v0.1 |

Names: the GitHub organization and repository are `azerbaijan-mcp`, packages are
`azerbaijan-mcp-<source>` and MCP Registry names are `io.github.azerbaijan-mcp/<source>`.

## Principles

- **Official data first.** Use official feeds and APIs. Scrape only when there is no alternative.
- **One server per source.** Small tool lists work better with LLMs than one 40-tool bundle.
- **Read-only, no personal data.** No logins, no seller phone numbers, no contact details.
- **Respect the source.** Honest User-Agent, rate limits, caching, and each site's terms and robots.txt.
  A server that scrapes a site whose terms forbid it ships as a local stdio server only, never hosted.
- **Attribute.** Every response says where the data came from.

The full policy, including the checklist for adding a source, is in [docs/data-policy.md](docs/data-policy.md).

## Use

Add this to your MCP client configuration (requires [uv](https://docs.astral.sh/uv/)):

```json
{
  "mcpServers": {
    "cbar": {
      "command": "uvx",
      "args": ["azerbaijan-mcp-cbar"]
    }
  }
}
```

In Claude Code: `claude mcp add cbar -- uvx azerbaijan-mcp-cbar`.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
uv run pytest              # offline tests
uv run pytest -m live      # contract tests against the real upstream services
uv run ruff check . && uv run ruff format --check .
uv run python scripts/release.py check   # registry metadata matches pyproject and README
```

See [docs/adding-a-server.md](docs/adding-a-server.md) to add a server and
[docs/releasing.md](docs/releasing.md) to release one.

## License

MIT. Unofficial project: not affiliated with or endorsed by any institution whose data it serves.
