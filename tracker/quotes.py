"""Shared quote model for all flight price sources."""

from dataclasses import dataclass, asdict, field


@dataclass
class Quote:
    """One priced round-trip option from one source for one date pair."""

    source: str            # short id, e.g. "google", "kiwi"
    source_name: str       # display name, e.g. "Google Flights"
    out_date: str          # YYYY-MM-DD
    ret_date: str          # YYYY-MM-DD
    price: float           # total round-trip price in the tracked currency
    currency: str
    airlines: list[str] = field(default_factory=list)
    stops_out: int | None = None
    stops_in: int | None = None
    duration_min: int | None = None  # total travel time when the source reports it
    booking_url: str = ""
    fare_type: str = "regular"       # "regular" | "student"

    def to_dict(self) -> dict:
        return asdict(self)
