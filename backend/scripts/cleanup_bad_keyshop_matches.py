from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.keyshop_common import classify_keyshop_product, product_title_from_url

CHECKED_SHOPS = {
    "Instant Gaming",
    "Kinguin",
    "G2A",
    "CDKeys",
    "Gamivo",
    "Fanatical",
    "GOG",
    "Epic Games",
    "EA App",
    "Eneba",
}
FORBIDDEN_SHOPS = {"Eneba"}


def main(apply: bool = False) -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(Game, Offer)
            .join(Offer, Offer.game_id == Game.id)
            .filter(Offer.shop_name.in_(CHECKED_SHOPS), Offer.in_stock == True)
            .all()
        )
        bad: list[tuple[Game, Offer, str, str]] = []
        for game, offer in rows:
            candidate = product_title_from_url(offer.affiliate_url)
            if offer.shop_name in FORBIDDEN_SHOPS:
                bad.append((game, offer, candidate, "eneba_disabled"))
                continue
            verdict = classify_keyshop_product(game.title, candidate, offer.affiliate_url)
            if not verdict["valid"]:
                bad.append((game, offer, candidate, str(verdict["reason"])))

        print(f"checked={len(rows)} bad={len(bad)} apply={apply}")
        for game, offer, candidate, reason in bad[:200]:
            print(
                f"{offer.shop_name}\t{offer.price_pln}\t{game.title}\t{game.slug}\t{reason}\t{candidate}\t{offer.affiliate_url}"
            )

        if apply:
            for _game, offer, _candidate, _reason in bad:
                offer.in_stock = False
            commit_with_retry(db)
            print(f"disabled={len(bad)}")
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    main(apply=args.apply)
