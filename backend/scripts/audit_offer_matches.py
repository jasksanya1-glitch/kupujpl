#!/usr/bin/env python3
"""Find and remove keyshop offers that don't match the game title."""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.keyshop_common import slugify, title_mismatch, upsert_keyshop_offer

OFFICIAL_SHOPS = frozenset({"Steam", "Epic Games"})

SHOP_SEARCH = {
    "CDKeys": ("app.parsers.cdkeys_parser", "search_cdkeys_price"),
    "Kinguin": ("app.parsers.kinguin_parser", "search_kinguin_price"),
    "Instant Gaming": ("app.parsers.instant_gaming_parser", "search_instant_gaming_price"),
    "Gamivo": ("app.parsers.gamivo_parser", "search_gamivo_price"),
    "G2A": ("app.parsers.g2a_parser", "search_g2a_price"),
    "Fanatical": ("app.parsers.fanatical_parser", "search_fanatical_price"),
    "Eneba": ("app.parsers.eneba_parser", "search_eneba_price"),
    "GOG": ("app.parsers.gog_parser", "search_gog_price"),
}


def _labels_from_url(url: str) -> list[str]:
    path = unquote(urlparse(url).path.strip("/"))
    labels: list[str] = []
    for part in path.split("/"):
        part = part.strip()
        if not part or part.isdigit():
            continue
        if part in {"pl", "en", "game", "store", "category", "product", "pc", "steam", "cd-key"}:
            continue
        if re.fullmatch(r"\d+", part):
            continue
        cleaned = re.sub(r"^\d+-", "", part)
        cleaned = cleaned.replace("_", "-")
        label = cleaned.replace("-", " ").strip()
        if len(label) >= 3:
            labels.append(label)
    return labels


def offer_mismatch(game_title: str, offer: Offer) -> bool:
    if offer.shop_name in OFFICIAL_SHOPS:
        return False
    url = offer.affiliate_url or ""
    if not url:
        return True
    for label in _labels_from_url(url):
        if title_mismatch(game_title, label):
            return True
    return False


def _load_search_fn(shop: str):
    import importlib

    module_name, attr = SHOP_SEARCH[shop]
    mod = importlib.import_module(module_name)
    return getattr(mod, attr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit keyshop offer title matches")
    parser.add_argument("--apply", action="store_true", help="Delete mismatched offers")
    parser.add_argument("--refresh", action="store_true", help="Re-fetch deleted offer pairs")
    parser.add_argument("--limit", type=int, default=0, help="Max refreshes (0=all)")
    args = parser.parse_args()

    db = SessionLocal()
    bad: list[tuple[Game, Offer]] = []
    try:
        rows = (
            db.query(Game, Offer)
            .join(Offer, Offer.game_id == Game.id)
            .filter(Offer.in_stock == True)
            .all()
        )
        for game, offer in rows:
            if offer_mismatch(game.title, offer):
                bad.append((game, offer))

        print(f"Checked {len(rows)} in-stock offers")
        print(f"Mismatched keyshop offers: {len(bad)}")
        for game, offer in bad[:40]:
            print(f"  [{game.id}] {game.title} | {offer.shop_name} {offer.price_pln} | {offer.affiliate_url[:90]}")
        if len(bad) > 40:
            print(f"  ... and {len(bad) - 40} more")

        if not args.apply:
            print("\nDry-run — pass --apply to delete.")
            return 0

        removed = 0
        refresh_pairs: list[tuple[Game, str]] = []
        for game, offer in bad:
            db.delete(offer)
            removed += 1
            refresh_pairs.append((game, offer.shop_name))
        commit_with_retry(db)
        print(f"Deleted {removed} offers")

        if not args.refresh or not refresh_pairs:
            return 0

        seen: set[tuple[int, str]] = set()
        refreshed = 0
        for game, shop in refresh_pairs:
            key = (game.id, shop)
            if key in seen or shop not in SHOP_SEARCH:
                continue
            seen.add(key)
            if args.limit and refreshed >= args.limit:
                break
            fn = _load_search_fn(shop)
            slug = slugify(game.title)
            if shop == "GOG":
                result = fn(game.title)
            else:
                result = fn(game.title, slug)
            url = result[0] if result else None
            price = result[1] if result and len(result) > 1 else None
            conf = result[2] if result and len(result) > 2 else None
            if url and price is not None:
                upsert_keyshop_offer(
                    db,
                    game,
                    shop,
                    url,
                    float(price),
                    match_confidence=float(conf) if conf is not None else None,
                )
                commit_with_retry(db)
                refreshed += 1
                print(f"  refreshed {game.title} / {shop} -> {price}")
            time.sleep(0.5 if shop != "Gamivo" else 2.0)

        print(f"Refreshed {refreshed} offers")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
