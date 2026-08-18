# Flight Price Tracker

Tracks round-trip prices for any number of routes and date windows — every
hour, from multiple sources including Indian booking sites and **student
fares** — and publishes a live dashboard with the full price history and
booking links. Trips whose dates have passed are kept as browsable archives.

**Live dashboard:** https://xthpb.github.io/flight-price-tracker/

## Adding or changing a trip

**From the dashboard:** the **+ Track a trip** button opens a form — pick the
airports (autocomplete over ~180 majors, or any IATA code), a single date or a
range for each leg, currency/cabin/passengers — and it commits the trip to
`config.json` for you. That needs a fine-grained GitHub token (Contents:
read & write on this repo) which is asked for once and kept in the browser;
without one, "Copy config snippet" gives you the JSON to paste in yourself.

**By hand:** edit `config.json` (directly on GitHub is fine) and commit.
Either way **the push triggers a run immediately**, so prices appear on the
dashboard within a few minutes, then refresh hourly. One object per trip in
the `trips` list:

```json
{
  "id": "ams-bcn-oct26",
  "route": {
    "origin": "AMS", "destination": "BCN",
    "origin_city": "Amsterdam", "destination_city": "Barcelona",
    "origin_country": "Netherlands", "destination_country": "Spain"
  },
  "dates": {
    "outbound": { "start": "2026-10-16", "end": "2026-10-18" },
    "return":   { "start": "2026-10-25", "end": "2026-10-27" }
  },
  "currency": "EUR"
}
```

- `id` — optional; names the trip's data directory (defaults to `origin-destination`).
  Give explicit ids when tracking the same route twice.
- `dates` — a `{start, end}` range, a single `"YYYY-MM-DD"`, or a list of
  either. Past dates are dropped automatically; when a trip's whole window has
  passed it is skipped and marked "ended" on the dashboard — never a failed run.
- Any key from `defaults` (passengers, cabin, currency, per-source settings)
  can be overridden per trip. `google.market` / `kiwi.market` pick the sales
  market; `origin_country`/`destination_country` are only needed for correct
  EaseMyTrip booking links.
- EaseMyTrip (incl. student fares) only runs for trips priced in INR.
- Keep windows modest: Google Flights is queried per date pair (capped at
  `google.max_pairs`, evenly sampled beyond that) and the whole run must fit
  the workflow's 25-minute budget.

Old trips can simply stay in the list as archives, or be deleted — deleting
one removes it from the dashboard (its data files remain in git history).

## How it works

```
GitHub Actions (hourly cron + push to config.json/tracker/**)
  └─ tracker/main.py                 one pass per trip with future dates
       ├─ sources/google_flights.py   Google Flights (fast-flights filter + parser)
       ├─ sources/kiwi.py             Kiwi.com public GraphQL search API
       ├─ sources/easemytrip.py       EaseMyTrip (Indian OTA) — regular AND student fares
       ├─ sources/amadeus.py          Amadeus flight offers        (optional, needs API key)
       └─ sources/travelpayouts.py    Aviasales cached prices      (optional, needs API token)
             │
             ▼
  docs/data/index.json           every configured trip + route/dates/active flag
  docs/data/<trip>/latest.json   every quote from the trip's newest check
  docs/data/<trip>/history.json  best price per source & date pair, every check
             │
             ▼
  docs/index.html                static dashboard (route picker) on GitHub Pages
```

Each run commits the refreshed data files, which both preserves the complete
history in git and redeploys the Pages site.

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
python3 -m http.server -d docs     # then open http://localhost:8000
```

`TRACKER_CONFIG` and `TRACKER_DATA_DIR` env vars override the config path and
output directory (handy for testing without touching docs/data).

## Notes

- Prices are per-trip totals for the configured passengers/cabin/currency and
  can change by booking time.
- EaseMyTrip prices international round trips as two one-way fares (that is how
  its own booking flow charges), so its quotes are the sum of the two directions.
- Student fares (EaseMyTrip · Student) require a valid student ID at booking and
  only some airlines offer them — often the price matches the regular fare.
- Other Indian OTAs (MakeMyTrip, Goibibo, Cleartrip, ixigo, Yatra, Wego) sit behind
  Akamai/Cloudflare bot protection and cannot be polled reliably by an unattended
  hourly job; EaseMyTrip is the major Indian OTA with an automatable API.
- All scraped endpoints are unofficial; a source failing is logged and skipped,
  never fatal — the run fails only if *no* active trip gets data from *any* source.
- The first tracked trip (AMS ⇄ DEL, Aug 2026) lives on under
  `docs/data/ams-del-aug26/`; its first day ran in EUR before the switch to INR
  and is preserved in `history-eur-archive.json`.
