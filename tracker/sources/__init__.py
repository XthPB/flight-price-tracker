"""Source registry: each module exposes fetch(config) -> list[Quote].

Keyless sources always run. Keyed sources run only when their
credentials are present in the environment.
"""

import os

from . import google_flights, kiwi, amadeus, travelpayouts


def active_sources() -> list:
    sources = [google_flights, kiwi]
    if os.environ.get("AMADEUS_CLIENT_ID") and os.environ.get("AMADEUS_CLIENT_SECRET"):
        sources.append(amadeus)
    if os.environ.get("TRAVELPAYOUTS_TOKEN"):
        sources.append(travelpayouts)
    return sources
