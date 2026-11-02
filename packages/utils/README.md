<!-- mcp-name: io.github.azerbaijan-mcp/utils -->

# azerbaijan-mcp-utils

Offline MCP tools for Azerbaijan: IBAN and phone checks, amounts in manat written in words, Latin and
Cyrillic transliteration, and the official holiday calendar. Nothing here uses the network: the tools
are plain functions, and the tests run with network access blocked.

## Tools

| Tool | What it does |
|---|---|
| `validate_iban(iban)` | Checks an Azerbaijani IBAN: `AZ`, 28 characters, the shape after the country code and the mod-97 check digits. Returns the IBAN in groups of four and its parts. |
| `format_phone(number)` | Normalises a phone number to `+994 50 123 45 67`, `+994501234567` and `050 123 45 67`, and says whether the prefix is mobile or a landline area. |
| `azn_in_words(amount, lang?, bir_min?)` | Writes an amount in manat and qəpik in words in `az`, `en` or `ru`. |
| `transliterate(text, direction)` | Converts between the Latin alphabet and the Cyrillic one of 1958-1991, `latin_to_cyrillic` or `cyrillic_to_latin`. |
| `holidays(year)` | The official non-working days of a year, with the decisions they come from and the rest days that were moved. |
| `working_days(start, end, week?)` | Counts the working days from `start` to `end`, both included, for a `five_day` or `six_day` week, and lists the others with their reasons. |

Things worth knowing:

- A valid IBAN has the right shape and check digits. That does not mean the account exists. A phone
  number with `valid_format` true has nine digits after `+994`; that does not mean it is in use. The
  operator of a mobile number is never reported, because numbers can move between networks.
- Amounts are exact: at most two decimals, never rounded, below one trillion. Pass a string such as
  `"1234.56"`; a float is read as its shortest text, so `0.1 + 0.2` is refused. `1 234,56` is understood.
  Azerbaijani writes `min` and `yüz` without `bir`; `bir_min` writes `bir min` for a single thousand, as
  many financial documents do. Russian numerals take the right gender and plural. The subunit is
  written `qəpik` in English too, because English spellings differ (gapik, gepik, qapik).
- The 32 letters of the Azerbaijani Latin alphabet and of the 1958 Cyrillic alphabet correspond one to
  one, so the conversion is exact in both directions. Letters outside the tables, such as the
  Russian-only `Я`, `Ю`, `Щ`, are left as they are and listed in `unchanged`.
- The calendar covers **2025 and 2026**. A year without a file is refused with the list of the years
  loaded, never guessed. A "working day" is one in the Ministry's production calendar: the weekly rest
  days (Saturday and Sunday in a five-day week, Sunday in a six-day week), the holidays, the Day of
  National Mourning, voting days and the rest days moved because a weekly rest day fell on a holiday
  are not working days. Shorter pre-holiday days still count as working days.
- Municipal elections day, 29 January 2025, is non-working where the vote is held; the Ministry counts
  it as a non-working day for the whole year's total, and so does this server.
- VÖEN and FIN checks are **not included**. The State Tax Service says the ninth digit of a VÖEN is set
  by a special algorithm and does not publish it, and no official source gives the values of the last
  digit, so a format check would only count digits. A FIN is a personal identifier with no published
  check.

## Install

Add to your MCP client configuration (requires [uv](https://docs.astral.sh/uv/)):

```json
{
  "mcpServers": {
    "utils": {
      "command": "uvx",
      "args": ["azerbaijan-mcp-utils"]
    }
  }
}
```

In Claude Code: `claude mcp add utils -- uvx azerbaijan-mcp-utils`.

## Rules and sources

| Tool | Rule | Source |
|---|---|---|
| `validate_iban` | 28 characters: `AZ`, two check digits, a four-letter bank code, 20 letters or digits; mod-97 equals 1 | ISO 13616 and the SWIFT IBAN Registry; the structure is also listed at [Wikipedia](https://en.wikipedia.org/wiki/International_Bank_Account_Number). The registry's example `AZ21NABZ00000000137010001944` is in the tests. |
| `format_phone` | Nine national digits (two-digit prefix and seven digits), trunk prefix `0`, country code `994`; mobile prefixes 10, 50, 51, 55, 60, 70, 77, 99; area codes 12, 18, 20-26, 36 | National Numbering Plan of Azerbaijan, ITU Operational Bulletin No. 1162 (15 December 2018), as summarised at [Wikipedia](https://en.wikipedia.org/wiki/Telephone_numbers_in_Azerbaijan) |
| `azn_in_words` | Azerbaijani, English and Russian numerals; manat and qəpik (манат, гяпик) | School textbooks at [e-derslik.edu.az](http://e-derslik.edu.az) for `min` and `yüz` without `bir`; the "bir min" style as in [birhesab.az](https://birhesab.az/az/hesablayici/azn-sozle/); [Russian Wikipedia](https://ru.wikipedia.org/wiki/Гяпик) for гяпик |
| `transliterate` | 32 letters of the Latin alphabet against 32 of the Cyrillic alphabet of 1958-1991 | [Azerbaijani alphabet](https://en.wikipedia.org/wiki/Azerbaijani_alphabet) and the table in [Essentials of Azerbaijani](https://minio.la.utexas.edu/webeditor-files/slavic/pdf/azeri.pdf) |
| `holidays`, `working_days` | The Ministry's production calendar, Labour Code articles 105 and 108, and the Cabinet decision on the Novruz, Ramadan and Qurban days | 2026: [Ministry of Labour and Social Protection of the Population](https://sosial.gov.az/faydali/istehsalat-teqvimi/2026-ci-ilin-istehsalat-teqvimi), Collegium decision of 11 December 2025, No. 3-17/3-5-31/2025, with Cabinet of Ministers decision No. 362 of 2 December 2025. 2025: [the Ministry's page](https://sosial.gov.az/faydali/istehsalat-teqvimi/2025-ci-ilin-istehsalat-teqvimi), Collegium decision of 16 December 2024, No. 3-17/3-5-31/2024, with Cabinet decisions No. 521 of 11 December 2024 (Novruz, Ramadan and Qurban days) and No. 499 of 28 November 2024 (moved working and rest days), and Central Election Commission decision No. 49/238 of 27 November 2024 (municipal elections day). |

The movable holidays (Ramadan and Qurban, and the Novruz days) are the ones the Cabinet decision sets
each year; `holidays` marks them `decree` and names the decision. The other holidays are `fixed` by the
Labour Code.

## Adding a year to the calendar

The Cabinet decision on the Novruz, Ramadan and Qurban days and the Ministry's production calendar for
the next year are published in December.

1. Open the Ministry's page for the year, <https://sosial.gov.az/faydali/istehsalat-teqvimi>.
2. Copy `src/azerbaijan_mcp_utils/data/calendar_2026.json` to `calendar_<year>.json` and change it to
   match the page: the Collegium decision and the Cabinet decisions it names, one entry per non-working
   day (a day with two holidays gets two entries), the rest days for the five-day and the six-day week,
   and the official totals.
3. Run `uv run pytest packages/utils`. The tests add up the working days of the file and compare them
   with the Ministry's own total for the five-day week, so a date copied wrongly fails the run.
4. Update "2025 and 2026" above and release a new version.

## Data source and terms

The package fetches nothing at run time. The calendar files hold dates, holiday names and decision
numbers copied by hand from the Ministry's public pages on 2026-11-02, not the text of the decisions.
Answers to the checklist in the repository's [data policy](../../docs/data-policy.md):

- **Terms:** the Ministry's pages state no terms. The calendars are public decisions published for
  general use, and only facts and decision numbers are kept here.
- **robots.txt, rate limit and cache:** not applicable, because nothing is requested at run time.
- **Attribution:** `holidays` and `working_days` name the decision and link to the Ministry's page.
- **Personal data:** none. The phone and IBAN checks work on what the caller sends, which is not
  stored or logged, and the tests use only the registry's example IBAN, numbers made from the
  numbering plan and invented values.
- **Publisher contacted:** no.
- **Decision:** go, as an offline tool.

Unofficial project, not affiliated with or endorsed by the Ministry of Labour and Social Protection of
the Population or any other institution named above.
