"""Kiwi.com source.

Uses the public umbrella GraphQL endpoint that powers kiwi.com search.
A single request covers the whole outbound/return date window, sorted by
price; we keep the cheapest itineraries per date pair.
"""

import logging

import requests

from ..quotes import Quote

log = logging.getLogger(__name__)

SOURCE_ID = "kiwi"
SOURCE_NAME = "Kiwi.com"

ENDPOINT = "https://api.skypicker.com/umbrella/v2/graphql?featureName=SearchReturnItinerariesQuery"

HEADERS = {
    "content-type": "application/json",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "origin": "https://www.kiwi.com",
    "referer": "https://www.kiwi.com/",
}

QUERY = """
query SearchReturnItinerariesQuery(
  $search: SearchReturnInput
  $filter: ItinerariesFilterInput
  $options: ItinerariesOptionsInput
) {
  returnItineraries(search: $search, filter: $filter, options: $options) {
    __typename
    ... on AppError { error: message }
    ... on Itineraries {
      metadata { itinerariesCount }
      itineraries {
        __typename
        ... on ItineraryReturn {
          id
          price { amount }
          priceEur { amount }
          duration
          bookingOptions {
            edges { node { bookingUrl price { amount } } }
          }
          outbound {
            duration
            sectorSegments { segment {
              source { localTime station { code } }
              destination { localTime station { code } }
              carrier { name code }
            } }
          }
          inbound {
            duration
            sectorSegments { segment {
              source { localTime station { code } }
              destination { localTime station { code } }
              carrier { name code }
            } }
          }
        }
      }
    }
  }
}
"""


def _variables(config):
    route = config["route"]
    out_dates = config["dates"]["outbound"]
    ret_dates = config["dates"]["return"]
    return {
        "search": {
            "itinerary": {
                "source": {"ids": [f"Station:airport:{route['origin']}"]},
                "destination": {"ids": [f"Station:airport:{route['destination']}"]},
                "outboundDepartureDate": {
                    "start": f"{out_dates[0]}T00:00:00",
                    "end": f"{out_dates[-1]}T23:59:59",
                },
                "inboundDepartureDate": {
                    "start": f"{ret_dates[0]}T00:00:00",
                    "end": f"{ret_dates[-1]}T23:59:59",
                },
            },
            "passengers": {
                "adults": config["passengers"]["adults"],
                "children": 0,
                "infants": 0,
                "adultsHoldBags": [0] * config["passengers"]["adults"],
                "adultsHandBags": [1] * config["passengers"]["adults"],
                "childrenHoldBags": [],
                "childrenHandBags": [],
            },
            "cabinClass": {"cabinClass": config["cabin"].upper().replace("-", "_"), "applyMixedClasses": False},
        },
        "filter": {
            "allowChangeInboundDestination": True,
            "allowChangeInboundSource": True,
            "allowDifferentStationConnection": True,
            "allowReturnFromDifferentCity": True,
            "enableSelfTransfer": True,
            "enableThrowAwayTicketing": False,
            "enableTrueHiddenCity": False,
            "maxStopsCount": 2,
            "transportTypes": ["FLIGHT"],
            "contentProviders": ["KIWI"],
            "flightsApiLimit": 25,
            "limit": config["kiwi"]["limit"],
        },
        "options": {
            "sortBy": "PRICE",
            "mergePriceDiffRule": "INCREASED",
            "currency": config["currency"].lower(),
            "apiUrl": None,
            "locale": "en",
            "market": config["kiwi"].get("market", "nl"),
            "partner": "skypicker",
            "partnerMarket": config["kiwi"].get("market", "nl"),
            "affilID": "skypicker",
            "storeSearch": False,
            "searchStrategy": "REDUCED",
            "abTestInput": {},
            "serverToken": None,
            "searchSessionId": None,
        },
    }


def _leg_info(sector):
    segments = [s["segment"] for s in sector["sectorSegments"]]
    carriers = [s["carrier"]["name"] for s in segments if s.get("carrier")]
    date = segments[0]["source"]["localTime"][:10]
    return date, len(segments) - 1, carriers


def fetch(config) -> list[Quote]:
    payload = {"query": QUERY, "variables": _variables(config)}
    r = requests.post(ENDPOINT, headers=HEADERS, json=payload, timeout=90)
    r.raise_for_status()
    node = r.json().get("data", {}).get("returnItineraries") or {}
    if node.get("__typename") != "Itineraries":
        raise RuntimeError(f"kiwi API error: {node.get('error') or node}")

    out_set = set(config["dates"]["outbound"])
    ret_set = set(config["dates"]["return"])
    currency = config["currency"]

    quotes = []
    for it in node.get("itineraries") or []:
        try:
            out_date, stops_out, carriers_out = _leg_info(it["outbound"])
            ret_date, stops_in, carriers_in = _leg_info(it["inbound"])
        except (KeyError, IndexError, TypeError):
            continue
        if out_date not in out_set or ret_date not in ret_set:
            continue

        price = float(it["price"]["amount"]) if currency != "EUR" else float(it["priceEur"]["amount"])
        edges = (it.get("bookingOptions") or {}).get("edges") or []
        booking_url = "https://www.kiwi.com" + edges[0]["node"]["bookingUrl"] if edges else ""
        duration = it.get("duration")

        quotes.append(Quote(
            source=SOURCE_ID,
            source_name=SOURCE_NAME,
            out_date=out_date,
            ret_date=ret_date,
            price=price,
            currency=currency,
            airlines=sorted(set(carriers_out + carriers_in)),
            stops_out=stops_out,
            stops_in=stops_in,
            duration_min=duration // 60 if duration else None,
            booking_url=booking_url,
        ))
    return quotes
