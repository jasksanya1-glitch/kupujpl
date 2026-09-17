"""Deactivate absurd price outliers (wrong SKU), including bad GOG/Epic matches."""
from __future__ import annotations

from collections import defaultdict

from app.core.database import SessionLocal, init_db
from app.core.db_retry import commit_with_retry
from app.core.offer_quality import STEAM_PRICE_RATIO_FLOOR, is_peer_price_outlier
from app.models.models import Offer

_STEAM_SHOPS = frozenset({"Steam", "Steam US"})


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        rows = (
            db.query(Offer)
            .filter(Offer.in_stock.is_(True), Offer.price_pln > 0)
            .all()
        )
        by_game: dict[int, list[Offer]] = defaultdict(list)
        for offer in rows:
            by_game[offer.game_id].append(offer)

        deactivated = 0
        for offers in by_game.values():
            prices = [float(o.price_pln) for o in offers if o.price_pln]
            steam = next(
                (float(o.price_pln) for o in offers if o.shop_name == "Steam"),
                None,
            )
            for offer in offers:
                if offer.shop_name in _STEAM_SHOPS:
                    continue
                price = float(offer.price_pln)
                others = list(prices)
                try:
                    others.remove(price)
                except ValueError:
                    pass
                bad_peer = is_peer_price_outlier(price, others)
                bad_steam = (
                    steam is not None
                    and steam >= 5
                    and price / steam < STEAM_PRICE_RATIO_FLOOR
                )
                if not (bad_peer or bad_steam):
                    continue
                offer.in_stock = False
                deactivated += 1

        commit_with_retry(db)
        print(f"deactivated_outliers={deactivated}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
