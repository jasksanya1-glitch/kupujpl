#!/usr/bin/env python3
"""Re-fetch Instant Gaming prices with EUR→PLN conversion fix."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import distinct

from app.core.database import SessionLocal
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.instant_gaming_parser import search_instant_gaming_price
from app.parsers.keyshop_common import slugify, upsert_keyshop_offer

SHOP = "Instant Gaming"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        game_ids = [
            row[0]
            for row in db.query(distinct(Offer.game_id))
            .filter(Offer.shop_name == SHOP)
            .all()
        ]
        games = db.query(Game).filter(Game.id.in_(game_ids)).order_by(Game.id).all()
        if args.limit:
            games = games[: args.limit]

        updated = removed = unchanged = 0
        for game in games:
            slug = slugify(game.title)
            result = search_instant_gaming_price(game.title, slug)
            url = result[0] if result else None
            price = result[1] if result and len(result) > 1 else None
            conf = result[2] if result and len(result) > 2 else None

            offer = (
                db.query(Offer)
                .filter(Offer.game_id == game.id, Offer.shop_name == SHOP)
                .first()
            )
            old = offer.price_pln if offer else None

            if not url or price is None:
                if offer:
                    removed += 1
                    if args.apply:
                        db.delete(offer)
                        commit_with_retry(db)
                continue

            if offer and abs((old or 0) - price) < 0.02:
                unchanged += 1
                continue

            print(f"{'FIX' if args.apply else 'DRY'} {game.title[:45]:45} {old} -> {price}")
            updated += 1
            if args.apply:
                upsert_keyshop_offer(
                    db,
                    game,
                    SHOP,
                    url,
                    float(price),
                    match_confidence=float(conf) if conf is not None else None,
                )
                commit_with_retry(db)
            time.sleep(1.0)

        print(f"games={len(games)} updated={updated} removed={removed} unchanged={unchanged}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
