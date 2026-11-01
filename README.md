# azerbaijan-mcp

Open-source [MCP](https://modelcontextprotocol.io) servers for Azerbaijani data and services. One small,
independently installable server per data source.

| Server | Package | Source | Status |
|---|---|---|---|
| [cbar](packages/cbar) | `azerbaijan-mcp-cbar` | Central Bank of Azerbaijan official exchange rates (XML feed) | v0.1, not released yet |
| opendata | | [opendata.az](https://opendata.az) (CKAN API) | planned |
| azstat | | State Statistical Committee open API | planned |
| utils | | Offline helpers: IBAN / VÖEN checks, holidays, AZN in words | planned |
| eqanun | | e-qanun.az legal acts | planned |

## Principles

- **Official data first.** Use official feeds and APIs. Scrape only when there is no alternative.
- **One server per source.** Small tool lists work better with LLMs than one 40-tool bundle.
- **Read-only, no personal data.** No logins, no seller phone numbers, no contact details.
- **Respect the source.** Honest User-Agent, rate limits, caching, and each site's terms and robots.txt.
  A server that scrapes a site whose terms forbid it ships as a local stdio server only, never hosted.
- **Attribute.** Every response says where the data came from.

## Use

Not on PyPI yet. From a checkout, add this to your MCP client configuration:

```json
{
  "mcpServers": {
    "cbar": {
      "command": "uvx",
      "args": ["--from", "/path/to/azerbaijan-mcp/packages/cbar", "azerbaijan-mcp-cbar"]
    }
  }
}
```

After the first release the arguments become just `["azerbaijan-mcp-cbar"]`.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
uv run pytest              # offline tests
uv run pytest -m live      # contract tests against the real upstream services
uv run ruff check . && uv run ruff format --check .
```

See [docs/adding-a-server.md](docs/adding-a-server.md) to add a server.

## License

MIT. Unofficial project: not affiliated with or endorsed by any institution whose data it serves.
