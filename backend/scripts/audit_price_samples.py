"""Audit sample games for offer/cover quality (RE4, Gothic Remake, regression)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.core.slug_lookup import resolve_game_slug
from app.models.models import Offer

SAMPLES = [
    ("resident-evil-4", 2050650),
    ("gothic-1-remake", None),
    ("cyberpunk-2077", 1091500),
]


def audit_game(db, slug: str, expected_appid: int | None) -> dict:
    game = resolve_game_slug(db, slug)
    if not game:
        return {"slug": slug, "found": False}
    offers = (
        db.query(Offer)
        .filter(Offer.game_id == game.id, Offer.in_stock == True)
        .order_by(Offer.price_pln)
        .all()
    )
    return {
        "slug": slug,
        "found": True,
        "title": game.title,
        "steam_appid": game.steam_appid,
        "expected_appid": expected_appid,
        "appid_ok": expected_appid is None or game.steam_appid == expected_appid,
        "cover_image": game.cover_image,
        "offers": [
            {
                "shop": o.shop_name,
                "price_pln": o.price_pln,
                "url": o.affiliate_url,
                "confidence": o.match_confidence,
                "low_confidence": o.match_confidence is not None and o.match_confidence < 0.55,
            }
            for o in offers
        ],
    }


def main() -> None:
    db = SessionLocal()
    try:
        report = [audit_game(db, slug, appid) for slug, appid in SAMPLES]
    finally:
        db.close()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
