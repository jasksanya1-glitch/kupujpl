"""Re-fetch GOG / Epic prices for offers not updated recently."""
from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta

from app.core.database import SessionLocal, init_db
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.epic_parser import update_epic_offer_for_game
from app.parsers.gog_parser import update_gog_offer_for_game

logger = logging.getLogger("refresh_stale_official")

SHOP_UPDATERS = {
    "GOG": update_gog_offer_for_game,
    "Epic Games": update_epic_offer_for_game,
}


def refresh_stale(
    *,
    shops: list[str],
    older_than_days: int = 14,
    limit: int | None = None,
    sleep_s: float = 0.35,
) -> dict[str, int]:
    init_db()
    cutoff = datetime.utcnow() - timedelta(days=older_than_days)
    stats = {
        "candidates": 0,
        "updated": 0,
        "unchanged_or_missing": 0,
        "errors": 0,
        "deactivated_missing": 0,
    }
    db = SessionLocal()
    try:
        q = (
            db.query(Offer.game_id, Offer.shop_name)
            .filter(
                Offer.shop_name.in_(shops),
                Offer.in_stock.is_(True),
                Offer.updated_at < cutoff,
            )
            .order_by(Offer.updated_at.asc())
        )
        if limit:
            q = q.limit(limit)
        rows = q.all()
        # Unique (game, shop) — one refresh per pair
        seen: set[tuple[int, str]] = set()
        work: list[tuple[int, str]] = []
        for gid, shop in rows:
            key = (gid, shop)
            if key in seen:
                continue
            seen.add(key)
            work.append(key)
        stats["candidates"] = len(work)
        print(f"candidates={len(work)} shops={shops} older_than_days={older_than_days}")

        for i, (gid, shop) in enumerate(work, 1):
            updater = SHOP_UPDATERS.get(shop)
            if not updater:
                continue
            game = db.query(Game).filter(Game.id == gid).first()
            if not game:
                continue
            try:
                before = (
                    db.query(Offer)
                    .filter(
                        Offer.game_id == gid,
                        Offer.shop_name == shop,
                        Offer.in_stock.is_(True),
                    )
                    .first()
                )
                prev = float(before.price_pln) if before and before.price_pln else None
                ok = bool(updater(db, game))
                commit_with_retry(db)
                after = (
                    db.query(Offer)
                    .filter(Offer.game_id == gid, Offer.shop_name == shop)
                    .order_by(Offer.updated_at.desc())
                    .first()
                )
                if ok and after and after.in_stock:
                    stats["updated"] += 1
                    if prev is not None and after.price_pln is not None:
                        if abs(float(after.price_pln) - prev) >= 0.01:
                            print(
                                f"[{i}/{len(work)}] {shop} {game.title[:40]!r} "
                                f"{prev:.2f} -> {float(after.price_pln):.2f}"
                            )
                else:
                    # Mark stale row out of stock when shop no longer returns a match
                    if before and before.in_stock:
                        before.in_stock = False
                        before.updated_at = datetime.utcnow()
                        commit_with_retry(db)
                        stats["deactivated_missing"] += 1
                    else:
                        stats["unchanged_or_missing"] += 1
            except Exception as exc:
                db.rollback()
                stats["errors"] += 1
                logger.warning("refresh failed game=%s shop=%s: %s", gid, shop, exc)
            if sleep_s > 0:
                time.sleep(sleep_s)
            if i % 50 == 0:
                print(f"progress {i}/{len(work)} {stats}")
        return stats
    finally:
        db.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--sleep", type=float, default=0.35)
    parser.add_argument(
        "--shops",
        default="GOG,Epic Games",
        help="Comma-separated official shops",
    )
    args = parser.parse_args()
    shops = [s.strip() for s in args.shops.split(",") if s.strip()]
    stats = refresh_stale(
        shops=shops,
        older_than_days=args.days,
        limit=args.limit or None,
        sleep_s=args.sleep,
    )
    print("DONE", stats)


if __name__ == "__main__":
    main()
