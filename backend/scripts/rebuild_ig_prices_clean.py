#!/usr/bin/env python3
"""Remove stale Instant Gaming offers, then rebuild with strict parser."""
from __future__ import annotations

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
    db = SessionLocal()
    try:
        game_ids = [
            row[0]
            for row in db.query(distinct(Offer.game_id))
            .filter(Offer.shop_name == SHOP)
            .all()
        ]
        print(f"snapshot games={len(game_ids)}", flush=True)

        deleted = db.query(Offer).filter(Offer.shop_name == SHOP).delete(synchronize_session=False)
        commit_with_retry(db)
        print(f"deleted stale offers={deleted}", flush=True)

        games = db.query(Game).filter(Game.id.in_(game_ids)).order_by(Game.id).all()
        restored = skipped = 0
        for idx, game in enumerate(games, 1):
            result = search_instant_gaming_price(game.title, slugify(game.title))
            url = result[0] if result else None
            price = result[1] if result and len(result) > 1 else None
            conf = result[2] if result and len(result) > 2 else None
            if url and price is not None:
                upsert_keyshop_offer(
                    db,
                    game,
                    SHOP,
                    url,
                    float(price),
                    match_confidence=float(conf) if conf is not None else None,
                )
                commit_with_retry(db)
                restored += 1
                print(f"[{idx}/{len(games)}] RESTORE {game.title[:45]} -> {price}", flush=True)
            else:
                skipped += 1
                print(f"[{idx}/{len(games)}] SKIP {game.title[:55]}", flush=True)
            time.sleep(0.35)

        print(f"done restored={restored} skipped={skipped}", flush=True)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
