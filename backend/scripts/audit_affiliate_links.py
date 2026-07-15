#!/usr/bin/env python3
"""Audit in-stock offers for affiliate/referral tracking."""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func

from app.core.affiliate import make_affiliate_link
from app.core.click_tracking import NO_COMMISSION_SHOPS, _has_tracking
from app.core.database import SessionLocal
from app.models.models import Game, Offer


def audit() -> dict:
    db = SessionLocal()
    try:
        games_total = db.query(func.count(Game.id)).scalar() or 0
        offers = (
            db.query(Game, Offer)
            .join(Offer, Offer.game_id == Game.id)
            .filter(Offer.in_stock.is_(True))
            .all()
        )

        by_shop_total: Counter[str] = Counter()
        by_shop_untracked: Counter[str] = Counter()
        untracked_offers: list[dict] = []
        games_with_offers: set[int] = set()
        games_all_monetized_tracked: set[int] = set()
        games_any_untracked_monetized: set[int] = set()
        games_no_offers: set[int] = set()

        all_game_ids = {gid for (gid,) in db.query(Game.id).all()}
        for game, offer in offers:
            games_with_offers.add(game.id)
            shop = offer.shop_name or "?"
            by_shop_total[shop] += 1
            final = make_affiliate_link(offer.affiliate_url or "", shop)
            tracked = _has_tracking(final, shop)
            if shop in NO_COMMISSION_SHOPS:
                continue
            if tracked:
                games_all_monetized_tracked.add(game.id)
            else:
                by_shop_untracked[shop] += 1
                games_any_untracked_monetized.add(game.id)
                if len(untracked_offers) < 30:
                    untracked_offers.append(
                        {
                            "slug": game.slug,
                            "title": game.title,
                            "shop": shop,
                            "price": offer.price_pln,
                            "raw_url": (offer.affiliate_url or "")[:120],
                            "final_url": final[:120],
                        }
                    )

        games_no_offers = all_game_ids - games_with_offers

        # Per-game: any monetized offer exists and all monetized offers tracked?
        game_monetized: dict[int, list[bool]] = defaultdict(list)
        for game, offer in offers:
            shop = offer.shop_name or ""
            if shop in NO_COMMISSION_SHOPS:
                continue
            final = make_affiliate_link(offer.affiliate_url or "", shop)
            game_monetized[game.id].append(_has_tracking(final, shop))

        games_monetized_ok = sum(
            1 for tracked_list in game_monetized.values() if tracked_list and all(tracked_list)
        )
        games_monetized_partial = sum(
            1 for tracked_list in game_monetized.values() if tracked_list and any(tracked_list) and not all(tracked_list)
        )
        games_monetized_none = sum(
            1 for tracked_list in game_monetized.values() if tracked_list and not any(tracked_list)
        )
        games_no_monetized = len(games_with_offers) - len(game_monetized)

        shop_rows = []
        for shop, total in sorted(by_shop_total.items(), key=lambda x: (-x[1], x[0])):
            bad = by_shop_untracked.get(shop, 0)
            shop_rows.append(
                {
                    "shop": shop,
                    "offers": total,
                    "untracked_monetized": bad,
                    "tracked_pct": round(100 * (total - bad) / total, 1) if shop not in NO_COMMISSION_SHOPS and total else None,
                    "no_commission": shop in NO_COMMISSION_SHOPS,
                }
            )

        return {
            "games_total": games_total,
            "games_with_offers": len(games_with_offers),
            "games_without_offers": len(games_no_offers),
            "in_stock_offers_total": len(offers),
            "monetized_offers_total": sum(
                1 for _, o in offers if (o.shop_name or "") not in NO_COMMISSION_SHOPS
            ),
            "untracked_monetized_offers": sum(by_shop_untracked.values()),
            "games_monetized_all_tracked": games_monetized_ok,
            "games_monetized_some_untracked": games_monetized_partial,
            "games_monetized_all_untracked": games_monetized_none,
            "games_only_steam_epic": games_no_monetized,
            "by_shop": shop_rows,
            "sample_untracked": untracked_offers,
        }
    finally:
        db.close()


if __name__ == "__main__":
    print(json.dumps(audit(), ensure_ascii=False, indent=2))
