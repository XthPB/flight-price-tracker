"""Orchestrator: run all active sources for every configured trip and
write the dashboard data files.

config.json holds a list of trips under "trips" (plus shared settings under
"defaults"). Date windows accept a list of YYYY-MM-DD strings, a single
string, or {"start": ..., "end": ...} ranges. Dates already in the past are
dropped automatically; a trip with no future dates left is skipped (kept in
the dashboard as an archived trip), and a run with nothing to track exits
cleanly instead of failing.

Outputs (under docs/data/, served by GitHub Pages):
  index.json            — every configured trip: route, dates, active flag
  <trip>/latest.json    — every quote from the trip's most recent run
  <trip>/history.json   — one entry per run: best price per (source, date pair)
"""

import json
import logging
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .sources import active_sources

log = logging.getLogger("tracker")

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("TRACKER_CONFIG", ROOT / "config.json"))
DATA_DIR = Path(os.environ.get("TRACKER_DATA_DIR", ROOT / "docs" / "data"))


def deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k] = deep_merge(merged[k], v)
        else:
            merged[k] = v
    return merged


def expand_dates(spec) -> list[str]:
    """Accept "YYYY-MM-DD", {"start","end"}, or a (nested) list of either."""
    if isinstance(spec, str):
        return [spec]
    if isinstance(spec, dict):
        start = date.fromisoformat(spec["start"])
        end = date.fromisoformat(spec["end"])
        if end < start:
            raise ValueError(f"date range end {end} before start {start}")
        return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    return sorted({d for item in spec for d in expand_dates(item)})


def trip_id(trip: dict) -> str:
    route = trip["route"]
    default = f"{route['origin']}-{route['destination']}".lower()
    return re.sub(r"[^a-z0-9-]", "", str(trip.get("id", default)).lower()) or default


def load_trips(raw_config: dict) -> list[dict]:
    defaults = raw_config.get("defaults", {})
    today = datetime.now(timezone.utc).date().isoformat()
    trips, seen = [], set()
    for entry in raw_config["trips"]:
        cfg = deep_merge(defaults, entry)
        tid = trip_id(cfg)
        if tid in seen:
            raise ValueError(f"duplicate trip id {tid!r} — give one of them an explicit \"id\"")
        seen.add(tid)
        out_all = expand_dates(cfg["dates"]["outbound"])
        ret_all = expand_dates(cfg["dates"]["return"])
        out_future = [d for d in out_all if d >= today]
        ret_future = [d for d in ret_all if d >= today]
        cfg["dates"] = {"outbound": out_future, "return": ret_future}
        trips.append({
            "id": tid,
            "config": cfg,
            "all_dates": {"outbound": out_all, "return": ret_all},
            "active": bool(out_future and ret_future),
        })
    return trips


def run_sources(config) -> list:
    quotes = []
    for module in active_sources():
        started = time.time()
        try:
            source_quotes = module.fetch(config)
            log.info("%s: %d quotes in %.1fs", module.SOURCE_ID, len(source_quotes), time.time() - started)
            quotes.extend(source_quotes)
        except Exception:
            log.exception("%s: source failed entirely", module.SOURCE_ID)
    return quotes


def best_per_source_pair(quotes) -> dict:
    best = {}
    for q in quotes:
        key = (q.source, q.out_date, q.ret_date)
        if key not in best or q.price < best[key].price:
            best[key] = q
    return best


def write_index(trips):
    # deterministic (no timestamp) so unchanged config produces no git churn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    index = {
        "trips": [
            {
                "id": t["id"],
                "route": t["config"]["route"],
                "currency": t["config"]["currency"],
                "cabin": t["config"].get("cabin", "economy"),
                "passengers": t["config"].get("passengers", {"adults": 1}),
                "dates": t["all_dates"],
                "active": t["active"],
            }
            for t in trips
        ],
    }
    (DATA_DIR / "index.json").write_text(json.dumps(index, separators=(",", ":")))


def write_outputs(trip, quotes, now_iso):
    config = trip["config"]
    trip_dir = DATA_DIR / trip["id"]
    trip_dir.mkdir(parents=True, exist_ok=True)

    latest = {
        "updated_at": now_iso,
        "route": config["route"],
        "currency": config["currency"],
        "dates": config["dates"],
        "quotes": [q.to_dict() for q in sorted(quotes, key=lambda q: q.price)],
    }
    (trip_dir / "latest.json").write_text(json.dumps(latest, separators=(",", ":")))

    history_path = trip_dir / "history.json"
    history = json.loads(history_path.read_text()) if history_path.exists() else []
    entry = {
        "t": now_iso,
        "q": [
            [q.source, q.out_date, q.ret_date, round(q.price, 2)]
            for q in best_per_source_pair(quotes).values()
        ],
    }
    history.append(entry)
    history_path.write_text(json.dumps(history, separators=(",", ":")))
    log.info("%s: wrote %d quotes to latest.json, history now has %d runs",
             trip["id"], len(quotes), len(history))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = json.loads(CONFIG_PATH.read_text())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    trips = load_trips(config)
    write_index(trips)

    active = [t for t in trips if t["active"]]
    for t in trips:
        if not t["active"]:
            log.info("%s: all dates in the past — skipping (archived)", t["id"])
    if not active:
        log.info("nothing to track — add a trip with future dates to config.json")
        return

    total = 0
    for trip in active:
        log.info("%s: checking %s -> %s", trip["id"],
                 trip["config"]["route"]["origin"], trip["config"]["route"]["destination"])
        quotes = run_sources(trip["config"])
        if not quotes:
            log.warning("%s: no source returned any quotes — keeping previous data", trip["id"])
            continue
        total += len(quotes)
        write_outputs(trip, quotes, now_iso)
        cheapest = min(quotes, key=lambda q: q.price)
        log.info(
            "%s: cheapest %s %.0f %s | %s -> %s | %s",
            trip["id"], trip["config"]["currency"], cheapest.price, cheapest.source,
            cheapest.out_date, cheapest.ret_date, ", ".join(cheapest.airlines),
        )

    if total == 0:
        log.error("no source returned any quotes for any active trip — failing the run")
        sys.exit(1)


if __name__ == "__main__":
    main()
