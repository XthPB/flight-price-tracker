"""Google Flights source.

Builds the Google Flights search URL with fast-flights' protobuf filter,
fetches the page directly with requests (adding an EU cookie-consent
bypass so the scrape also works from EEA IPs), and parses the embedded
results with fast-flights' parser.
"""

import logging
import time

import requests
from fast_flights import FlightQuery, Passengers, create_query
from fast_flights.exceptions import FlightsNotFound
from fast_flights.parser import parse

from ..quotes import Quote

log = logging.getLogger(__name__)

SOURCE_ID = "google"
SOURCE_NAME = "Google Flights"

# SOCS/CONSENT cookies skip the "Before you continue to Google" wall on EEA IPs.
CONSENT_COOKIES = {
    "CONSENT": "PENDING+987",
    "SOCS": "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiA_LyaBg",
}
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
# From datacenter IPs (e.g. GitHub Actions) Google often throttles: it returns a
# page with no results and fast-flights raises FlightsNotFound("received error").
# That is IP-level throttling, not a transient blip — retrying in a few seconds
# does not help and just burns the workflow's time budget, so we fail that pair
# fast and only retry genuine network/HTTP errors.
RETRIES = 2


def _build_query(origin, destination, out_date, ret_date, adults, cabin, currency):
    return create_query(
        flights=[
            FlightQuery(date=out_date, from_airport=origin, to_airport=destination),
            FlightQuery(date=ret_date, from_airport=destination, to_airport=origin),
        ],
        trip="round-trip",
        seat=cabin,
        passengers=Passengers(adults=adults),
        currency=currency,
    )


def _spread(items: list, n: int) -> list:
    """Pick n items evenly spread across the list."""
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def _fetch_pair(query, market) -> list:
    url = query.url() + f"&gl={market}"
    last_err = None
    for attempt in range(RETRIES):
        try:
            r = requests.get(url, cookies=CONSENT_COOKIES, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return list(parse(r.text))
        except FlightsNotFound:
            # throttled or genuinely no flights — retrying won't change it
            raise
        except Exception as e:  # HTTP errors, timeouts, transient network issues
            last_err = e
            time.sleep(2)
    raise last_err


def fetch(config) -> list[Quote]:
    route = config["route"]
    currency = config["currency"]
    adults = config["passengers"]["adults"]
    cabin = config["cabin"]
    delay = config["google"]["request_delay_seconds"]
    per_pair = config["google"]["max_results_per_pair"]
    market = config["google"].get("market", "US")

    quotes = []
    pairs = [(o, r) for o in config["dates"]["outbound"] for r in config["dates"]["return"]]
    max_pairs = config["google"].get("max_pairs", 60)
    if len(pairs) > max_pairs:
        log.warning("google: %d date pairs exceeds max_pairs=%d, sampling evenly", len(pairs), max_pairs)
        pairs = _spread(pairs, max_pairs)
    for i, (out_date, ret_date) in enumerate(pairs):
        query = _build_query(route["origin"], route["destination"], out_date, ret_date,
                             adults, cabin, currency)
        try:
            results = _fetch_pair(query, market)
        except Exception as e:
            log.warning("google: %s -> %s failed: %s", out_date, ret_date, e)
            continue

        results.sort(key=lambda f: f.price if f.price else 1e12)
        for fl in results[:per_pair]:
            if not fl.price:
                continue
            legs = fl.flights or []
            quotes.append(Quote(
                source=SOURCE_ID,
                source_name=SOURCE_NAME,
                out_date=out_date,
                ret_date=ret_date,
                price=float(fl.price),
                currency=currency,
                airlines=sorted(set(fl.airlines or [])),
                stops_out=max(len(legs) - 1, 0) if legs else None,
                stops_in=None,  # Google's result rows only detail the outbound legs
                duration_min=sum(leg.duration or 0 for leg in legs) or None,
                booking_url=query.url() + f"&gl={market}",
            ))
        if i < len(pairs) - 1:
            time.sleep(delay)
    return quotes
