"""Travelpayouts / Aviasales cached-prices source (optional, keyed).

Runs only when TRAVELPAYOUTS_TOKEN is set (free token from
travelpayouts.com). Prices are cached from recent Aviasales searches,
so they lag live prices slightly but cost one request for the whole
month grid.
"""

import logging
import os

import requests

from ..quotes import Quote

log = logging.getLogger(__name__)

SOURCE_ID = "travelpayouts"
SOURCE_NAME = "Aviasales (cached)"

ENDPOINT = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


def fetch(config) -> list[Quote]:
    route = config["route"]
    out_set = set(config["dates"]["outbound"])
    ret_set = set(config["dates"]["return"])
    month = config["dates"]["outbound"][0][:7]

    r = requests.get(
        ENDPOINT,
        params={
            "origin": route["origin"],
            "destination": route["destination"],
            "departure_at": month,
            "return_at": month,
            "currency": config["currency"].lower(),
            "sorting": "price",
            "limit": 1000,
            "one_way": "false",
            "token": os.environ["TRAVELPAYOUTS_TOKEN"],
        },
        timeout=60,
    )
    r.raise_for_status()
    data = r.json().get("data", [])

    quotes = []
    for item in data:
        out_date = (item.get("departure_at") or "")[:10]
        ret_date = (item.get("return_at") or "")[:10]
        if out_date not in out_set or ret_date not in ret_set:
            continue
        link = item.get("link") or ""
        quotes.append(Quote(
            source=SOURCE_ID,
            source_name=SOURCE_NAME,
            out_date=out_date,
            ret_date=ret_date,
            price=float(item["price"]),
            currency=config["currency"],
            airlines=[item["airline"]] if item.get("airline") else [],
            stops_out=item.get("transfers"),
            stops_in=item.get("return_transfers"),
            duration_min=item.get("duration"),
            booking_url=f"https://www.aviasales.com{link}" if link else "",
        ))
    return quotes
