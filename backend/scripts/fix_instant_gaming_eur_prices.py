"""Fix old Instant Gaming offers saved as raw EUR in price_pln.

Older scans sometimes stored the EUR search result (e.g. 0.99) directly in
Offer.price_pln. Re-read the product page with currency=PLN and update those
offers in place.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.instant_gaming_parser import _product_page_price_pln
from app.parsers.keyshop_common import classify_keyshop_product


def _instant_gaming_product_url(url: str) -> str | None:
    if not url:
        return None
    if "instant-gaming.com" not in url:
        return None
    parsed = urlparse(url)
    path = parsed.path or ""
    match = re.search(r"/pl/\d+-[^/?#]+/?", path)
    if not match:
        return None
    return f"https://www.instant-gaming.com{match.group(0)}"


def _title_from_ig_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path or ""
    match = re.search(r"/pl/\d+-([^/?#]+)/?", path)
    if not match:
        return ""
    raw = match.group(1)
    raw = re.sub(r"-(pc|mac|game|steam|gog|epic|europe|global)$", "", raw, flags=re.I)
    return raw.replace("-", " ")


def _bad_title_match(game_title: str, product_title: str) -> tuple[bool, float]:
    verdict = classify_keyshop_product(game_title, product_title, min_score=0.62)
    return not bool(verdict["valid"]), float(verdict["score"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-price", type=float, default=35.0)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay-sec", type=float, default=0.4)
    args = parser.parse_args()

    db = SessionLocal()
    checked = updated = skipped = 0
    try:
        rows = (
            db.query(Offer, Game)
            .join(Game, Game.id == Offer.game_id)
            .filter(
                Offer.shop_name == "Instant Gaming",
                Offer.in_stock == True,
                Offer.price_pln > 0,
                Offer.price_pln <= args.max_price,
            )
            .order_by(Offer.price_pln.asc())
            .limit(args.limit)
            .all()
        )
        for offer, game in rows:
            checked += 1
            product_url = _instant_gaming_product_url(offer.affiliate_url)
            if not product_url:
                skipped += 1
                continue
            product_title = _title_from_ig_url(product_url)
            bad_match, score = _bad_title_match(game.title, product_title)
            if bad_match:
                print(
                    f"DISABLE {game.title[:70]} | {offer.price_pln:.2f} | "
                    f"score={score:.2f} | {product_title[:80]} | {product_url}"
                )
                if not args.dry_run:
                    offer.in_stock = False
                    updated += 1
                continue
            price_pln = _product_page_price_pln(product_url)
            if price_pln is None:
                skipped += 1
                continue
            old = float(offer.price_pln)
            # Only update when the product page gives a materially higher PLN
            # price. This avoids touching legitimate already-PLN cheap offers.
            if price_pln >= old * 2.5 and price_pln > old + 1.0:
                print(f"{game.title[:70]} | {old:.2f} -> {price_pln:.2f} | {product_url}")
                if not args.dry_run:
                    offer.price_pln = price_pln
                    updated += 1
            else:
                skipped += 1
            time.sleep(max(0.0, args.delay_sec))
        if not args.dry_run:
            commit_with_retry(db)
        print(f"checked={checked} updated={updated} skipped={skipped} dry_run={args.dry_run}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
