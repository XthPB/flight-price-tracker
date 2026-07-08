"""Amadeus Flight Offers source (optional, keyed).

Runs only when AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET are set.
The free self-service tier has a small monthly quota, so instead of the
full date grid we only query a capped number of date pairs (spread
across the grid) each run.
"""

import logging
import os

import requests

from ..quotes import Quote

log = logging.getLogger(__name__)

SOURCE_ID = "amadeus"
SOURCE_NAME = "Amadeus"

BASE = os.environ.get("AMADEUS_BASE_URL", "https://test.api.amadeus.com")


def _token() -> str:
    r = requests.post(
        f"{BASE}/v1/security/oauth2/token",
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["AMADEUS_CLIENT_ID"],
            "client_secret": os.environ["AMADEUS_CLIENT_SECRET"],
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _spread(items: list, n: int) -> list:
    """Pick n items evenly spread across the list."""
    if len(items) <= n:
        return items
    step = (len(items) - 1) / (n - 1)
    return [items[round(i * step)] for i in range(n)]


def fetch(config) -> list[Quote]:
    route = config["route"]
    currency = config["currency"]
    max_pairs = config.get("amadeus", {}).get("max_pairs", 6)

    pairs = [(o, r) for o in config["dates"]["outbound"] for r in config["dates"]["return"]]
    pairs = _spread(pairs, max_pairs)

    token = _token()
    headers = {"Authorization": f"Bearer {token}"}
    quotes = []
    for out_date, ret_date in pairs:
        try:
            r = requests.get(
                f"{BASE}/v2/shopping/flight-offers",
                headers=headers,
                params={
                    "originLocationCode": route["origin"],
                    "destinationLocationCode": route["destination"],
                    "departureDate": out_date,
                    "returnDate": ret_date,
                    "adults": config["passengers"]["adults"],
                    "currencyCode": currency,
                    "max": 3,
                },
                timeout=60,
            )
            r.raise_for_status()
            offers = r.json().get("data", [])
        except Exception as e:
            log.warning("amadeus: %s -> %s failed: %s", out_date, ret_date, e)
            continue

        carriers_dict = {}
        for offer in offers:
            price = float(offer["price"]["grandTotal"])
            itineraries = offer.get("itineraries", [])
            stops = [len(i.get("segments", [])) - 1 for i in itineraries]
            codes = {s["carrierCode"] for i in itineraries for s in i.get("segments", [])}
            quotes.append(Quote(
                source=SOURCE_ID,
                source_name=SOURCE_NAME,
                out_date=out_date,
                ret_date=ret_date,
                price=price,
                currency=offer["price"].get("currency", currency),
                airlines=sorted(codes),
                stops_out=stops[0] if stops else None,
                stops_in=stops[1] if len(stops) > 1 else None,
                duration_min=None,
                booking_url=(
                    "https://www.google.com/travel/flights?q="
                    f"flights%20from%20{route['origin']}%20to%20{route['destination']}"
                    f"%20on%20{out_date}%20return%20{ret_date}"
                ),
            ))
    return quotes
