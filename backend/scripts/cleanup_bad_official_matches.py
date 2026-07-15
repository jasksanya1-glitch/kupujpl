from __future__ import annotations

from app.core.database import SessionLocal
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.keyshop_common import classify_keyshop_product, product_title_from_url

SHOPS = {"GOG", "Epic Games", "EA App"}


def main(apply: bool = False) -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(Game, Offer)
            .join(Offer, Offer.game_id == Game.id)
            .filter(Offer.shop_name.in_(SHOPS), Offer.in_stock == True)
            .all()
        )
        bad: list[tuple[Game, Offer, str, str]] = []
        for game, offer in rows:
            candidate = product_title_from_url(offer.affiliate_url)
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
