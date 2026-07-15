#!/usr/bin/env python3
"""Health probe: sample top games × shops, suggest disabled list."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.database import BASE_DIR, SessionLocal
from app.models.models import Game
from app.parsers.game_catalog_filter import exclude_hidden_games_query
from app.parsers.offer_fetch_remote import fetch_remote_offers
from app.parsers.shop_scan_config import EXPECTED_SHOPS, get_active_scan_shops

logger = logging.getLogger("probe_shop_health")
OUT_PATH = Path(BASE_DIR) / "tmp" / "shop_health.json"


def _sample_games(db, limit: int) -> list[Game]:
    return (
        exclude_hidden_games_query(db.query(Game))
        .filter(Game.steam_enriched == True)
        .order_by(Game.steam_review_count.desc().nulls_last())
        .limit(limit)
        .all()
    )


def run_probe(*, sample_size: int = 20) -> dict:
    db = SessionLocal()
    try:
        games = _sample_games(db, sample_size)
    finally:
        db.close()

    shops = list(get_active_scan_shops())
    hits: dict[str, int] = {s: 0 for s in shops}
    tries: dict[str, int] = {s: 0 for s in shops}

    for game in games:
        for shop in shops:
            tries[shop] += 1
            rows = fetch_remote_offers(game.title, shops=(shop,))
            if rows:
                hits[shop] += 1

    rates = {
        s: round(hits[s] / max(tries[s], 1) * 100, 1)
        for s in shops
    }
    suggest_disable = [s for s in shops if rates[s] < 5.0]

    payload = {
        "probed_at": datetime.utcnow().isoformat() + "Z",
        "sample_size": len(games),
        "hit_rate_pct": rates,
        "suggest_disable": suggest_disable,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=20)
    args = parser.parse_args()
    result = run_probe(sample_size=args.sample)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
