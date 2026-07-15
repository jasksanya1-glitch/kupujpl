#!/usr/bin/env python3
"""Remove all games from DB except Tier A top-5000 list."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func

from app.core.database import SessionLocal
from app.core.game_catalog_filter import VISIBLE_COUNT_CACHE
from app.models.models import Game, Offer
from app.parsers.steam_catalog import refresh_category_counts
from app.parsers.tier_a_top5000 import load_tier_a_cache, rebuild_tier_a_cache


def _keep_ids(*, rebuild: bool) -> tuple[set[int], dict]:
    cache = load_tier_a_cache()
    if rebuild or not cache.get("list_ready"):
        cache = rebuild_tier_a_cache()
    keep: set[int] = set()
    for row in cache.get("games") or []:
        gid = row.get("game_id")
        if gid is not None:
            keep.add(int(gid))
    return keep, cache


def main() -> int:
    parser = argparse.ArgumentParser(description="Trim catalog to Tier A top-5000 only")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete games (default: dry-run only)",
    )
    parser.add_argument(
        "--rebuild-list",
        action="store_true",
        help="Rebuild tier_a_top5000.json before trim",
    )
    parser.add_argument("--batch", type=int, default=500, help="Delete batch size")
    args = parser.parse_args()

    keep, cache = _keep_ids(rebuild=args.rebuild_list)
    if not keep:
        print("Tier A list is empty — run with --rebuild-list or wait for daily rebuild.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        total = db.query(func.count(Game.id)).scalar() or 0
        keep_in_db = db.query(func.count(Game.id)).filter(Game.id.in_(keep)).scalar() or 0
        to_delete = total - keep_in_db
        offers_on_trim = (
            db.query(func.count(Offer.id))
            .filter(Offer.game_id.notin_(keep))
            .scalar()
            or 0
        )

        print(f"Tier A list: {len(keep)} games (cache count={cache.get('count')}, version={cache.get('version')})")
        print(f"DB total: {total} games")
        print(f"Will keep: {keep_in_db} (missing from DB: {len(keep) - keep_in_db})")
        print(f"Will delete: {to_delete} games, ~{offers_on_trim} offers")

        if not args.apply:
            print("\nDry-run — pass --apply to delete.")
            return 0

        deleted = 0
        while True:
            batch_ids = [
                row[0]
                for row in db.query(Game.id)
                .filter(Game.id.notin_(keep))
                .limit(args.batch)
                .all()
            ]
            if not batch_ids:
                break
            db.query(Game).filter(Game.id.in_(batch_ids)).delete(synchronize_session=False)
            db.commit()
            deleted += len(batch_ids)
            print(f"  deleted {deleted}/{to_delete}…")

        refresh_category_counts(db)
        db.commit()

        if VISIBLE_COUNT_CACHE.is_file():
            VISIBLE_COUNT_CACHE.unlink(missing_ok=True)

        remaining = db.query(func.count(Game.id)).scalar() or 0
        print(f"Done. Remaining games: {remaining}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
