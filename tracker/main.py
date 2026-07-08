"""Orchestrator: run all active sources and write the dashboard data files.

Outputs (under docs/data/, served by GitHub Pages):
  latest.json  — every quote from the most recent run, full detail
  history.json — one entry per run: best price per (source, date pair),
                 kept compact so the file grows slowly
"""

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .sources import active_sources

log = logging.getLogger("tracker")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "docs" / "data"


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


def write_outputs(config, quotes, now_iso):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    latest = {
        "updated_at": now_iso,
        "route": config["route"],
        "currency": config["currency"],
        "dates": config["dates"],
        "quotes": [q.to_dict() for q in sorted(quotes, key=lambda q: q.price)],
    }
    (DATA_DIR / "latest.json").write_text(json.dumps(latest, separators=(",", ":")))

    history_path = DATA_DIR / "history.json"
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
    log.info("wrote %d quotes to latest.json, history now has %d runs", len(quotes), len(history))


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = json.loads((ROOT / "config.json").read_text())
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    quotes = run_sources(config)
    if not quotes:
        log.error("no source returned any quotes — keeping previous data, failing the run")
        sys.exit(1)

    write_outputs(config, quotes, now_iso)
    cheapest = min(quotes, key=lambda q: q.price)
    log.info(
        "cheapest: %s %.0f %s | %s -> %s | %s",
        config["currency"], cheapest.price, cheapest.source,
        cheapest.out_date, cheapest.ret_date, ", ".join(cheapest.airlines),
    )


if __name__ == "__main__":
    main()
