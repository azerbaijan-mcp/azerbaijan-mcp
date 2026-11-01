<!-- mcp-name: io.github.azerbaijan-mcp/cbar -->

# azerbaijan-mcp-cbar

MCP server for the **official exchange rates of the Central Bank of the Republic of Azerbaijan (CBAR)**.
It reads CBAR's public XML feed (`https://cbar.az/currencies/DD.MM.YYYY.xml`): no API key, no scraping.

## Tools

| Tool | What it does |
|---|---|
| `get_rates(date?, codes?)` | Official AZN rates for 38 currencies and 4 precious metals. `date` is `YYYY-MM-DD` (default: today, Baku time). `codes` filters, for example `["USD", "EUR"]`. |
| `convert(amount, from_currency, to_currency, date?)` | Converts through AZN with the official rates. `AZN` is accepted as a code. |

Things worth knowing:

- Rates are AZN per `nominal` units. Seven currencies are quoted per 100 (JPY, KRW, KZT, HUF, UZS,
  PKR, RUB). `per_unit` is already divided.
- Metals are AZN per troy ounce.
- CBAR publishes no new sheet on weekends and public holidays. The response says which sheet it used
  (`sheet_date`, `note`).
- These are official reference rates, not bank buy/sell rates.

## Install

Add to your MCP client configuration (requires [uv](https://docs.astral.sh/uv/)):

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

## Data source and terms

The data is published by CBAR at <https://cbar.az/currency/rates>, which invites importing the XML URL
into applications. The page states no licence or reuse conditions, so this server relies on that
implied permission, caches responses (past dates forever, today for 10 minutes) and sends an honest
User-Agent. Every response carries an attribution field. Unofficial project, not affiliated with or
endorsed by CBAR.

`tests/fixtures/rates-2026-10-30.xml` is a snapshot of the public feed for 2026-10-30.
