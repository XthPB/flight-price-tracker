# AMS ⇄ DEL Flight Price Tracker

Tracks round-trip prices between **Amsterdam (AMS)** and **New Delhi (DEL)** —
outbound **Aug 8–14, 2026**, return **Aug 24–31, 2026** — every hour, from
multiple sources, and publishes a live dashboard with the full price history
and booking links.

**Live dashboard:** https://xthpb.github.io/flight-price-tracker/

## How it works

```
GitHub Actions (hourly cron)
  └─ tracker/main.py
       ├─ sources/google_flights.py   Google Flights (via fast-flights protobuf filter + parser)
       ├─ sources/kiwi.py             Kiwi.com public GraphQL search API
       ├─ sources/amadeus.py          Amadeus flight offers        (optional, needs API key)
       └─ sources/travelpayouts.py    Aviasales cached prices      (optional, needs API token)
             │
             ▼
  docs/data/latest.json    every quote from the newest check (full detail + booking links)
  docs/data/history.json   best price per source & date pair for every past check
             │
             ▼
  docs/index.html          static dashboard served by GitHub Pages
```

Each hourly run commits the refreshed data files, which both preserves the
complete history in git and redeploys the Pages site.

## Configuration

`config.json` holds the route, the outbound/return date windows, passengers,
cabin and currency. Edit it and the next run picks it up.

## Adding the optional keyed sources

Two more sources activate automatically when their credentials exist as
repository secrets (Settings → Secrets and variables → Actions):

| Source | Secrets | Where to get them |
|---|---|---|
| Amadeus | `AMADEUS_CLIENT_ID`, `AMADEUS_CLIENT_SECRET` | free self-service account at developers.amadeus.com |
| Aviasales/Travelpayouts | `TRAVELPAYOUTS_TOKEN` | free token at travelpayouts.com |

## Running locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m tracker.main
open docs/index.html   # or: python3 -m http.server -d docs
```

## Notes

- Prices are totals for 1 adult, economy, in EUR, and can change by booking time.
- Google Flights and Kiwi are scraped/unofficial endpoints; a source failing is
  logged and skipped, never fatal — the run fails only if *no* source returns data.
