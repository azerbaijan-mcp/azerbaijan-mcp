# Data and legal policy

How servers in this repo get their data and what they must do with it. This is a working policy, not legal advice.

## Rules

Scraping means taking data out of pages made for people, or out of an undocumented endpoint behind a site's own front end. Feeds, APIs and open-data portals made for programs are not scraping.

1. **Official data first.** Use an official feed, API or open-data portal. Scrape a site only when no official source exists and its terms allow automated access.
2. **Read-only.** A server never logs in, posts, buys or changes anything at the source.
3. **No personal data.** Never return or store names, phone numbers, emails, ID numbers or addresses of private people.
4. **Attribute.** Every response names the source and links to it. Say what the data is not (for example "not bank buy/sell rates").
5. **Terms win over robots.txt.** If a site's terms forbid automated access, there is no server for that site unless the operator agrees in writing.

## Polite client

- Send an honest User-Agent: `azerbaijan-mcp-<server>/<version>`.
- Respect robots.txt. When the terms are stricter, the terms win.
- At most 1 request per second per host from one server process.
- Cache data that cannot change (past dates, finished periods) for the life of the process; cache anything else for minutes, not seconds.
- Stop on 403, 429 or a bot challenge and say so. No proxies, stealth browsers, CAPTCHA solving or other circumvention.
- Bound every response: cap rows, bytes and pages.
- Retry at most once, and only for network errors and 5xx.

## Hosting

A server is hosted only when its source is official or open and allows it. A server for a site whose terms restrict automated access ships as a local stdio server, runs from the user's own connection and is never offered as a hosted service.

## Before adding a source

Copy this checklist into the server's issue and fill it in:

- [ ] Publisher, and why it is the official or best source
- [ ] Terms or licence URL, the clauses on automated access, date read; look in the FAQ and About pages too, not only a terms page
- [ ] robots.txt snapshot and date
- [ ] Data licence and attribution wording (for example CC0, CC-BY)
- [ ] Rate limit and cache decided
- [ ] Personal data check: nothing about private people is returned or stored
- [ ] Publisher contacted: reply, or no reply, recorded
- [ ] Decision: go, local-only or no-go, with the reason

Every server README has a "Data source and terms" section with the answers.

## Sources (as of 2026-11-01)

| Source | Access | Terms or licence | Decision |
|---|---|---|---|
| CBAR exchange rates | Official XML feed | The rates page states no licence or reuse terms and invites importing the XML URL | Go: attribute, cache, honest User-Agent |
| opendata.az | CKAN API (`package_search`, `package_show`) | The portal's FAQ (updated 2025-04-08) defines open data as usable and shareable by everyone and invites developers to build on the data and the API; each dataset has its own licence, mostly CC0 | Go: attribute, return each dataset's licence and flag missing ones, fetch files only from allowed hosts |
| State Statistical Committee (azstat) | Undocumented JSON API (`tables`, `data`) | No terms of its own; asks users to cite the source. opendata.az lists this API among the files of most of the Committee's datasets, all CC0, and its FAQ invites reuse | Go: cite the Committee, cache, honest User-Agent, contract test, report tables the API leaves ambiguous |
| e-qanun.az | No official API | Not reviewed | Blocked until the Ministry of Justice answers |
| Classifieds and job sites | No official API found | Not reviewed; at least one user agreement appears to restrict automated access | Not started: terms review comes first |

## Takedown and contact

If you operate a source this project uses and want changes or removal, open an issue in this repository's tracker. Access is changed or removed promptly.
