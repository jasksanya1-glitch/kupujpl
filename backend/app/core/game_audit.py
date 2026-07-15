"""Game catalog health metrics for diagnostics."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.slug_lookup import _trailing_digits
from app.models.models import Game, Offer


def _generic_header_cover(cover: str | None, appid: int | None) -> bool:
    if not cover or not appid:
        return False
    return cover.rstrip("/").endswith(f"/apps/{appid}/header.jpg")


def audit_game_catalog(db: Session) -> dict[str, Any]:
    total = db.query(func.count(Game.id)).scalar() or 0
    enriched = (
        db.query(func.count(Game.id)).filter(Game.steam_enriched == True).scalar() or 0
    )
    not_enriched = (
        db.query(func.count(Game.id))
        .filter(Game.steam_appid.isnot(None), Game.steam_enriched == False)
        .scalar()
        or 0
    )

    zero_offers_sq = (
        db.query(Offer.game_id)
        .filter(Offer.in_stock == True)
        .group_by(Offer.game_id)
        .subquery()
    )
    zero_offers = (
        db.query(func.count(Game.id))
        .filter(Game.steam_appid.isnot(None))
        .outerjoin(zero_offers_sq, Game.id == zero_offers_sq.c.game_id)
        .filter(zero_offers_sq.c.game_id.is_(None))
        .scalar()
        or 0
    )

    mistaken_stubs: list[dict[str, Any]] = []
    for game in db.query(Game).filter(Game.slug.like("gra-%")).limit(20):
        if re.fullmatch(r"gra-\d+-\d+", game.slug):
            mistaken_stubs.append(
                {"slug": game.slug, "steam_appid": game.steam_appid, "title": game.title}
            )

    short_suffix: list[dict[str, Any]] = []
    for game_id, slug, steam_appid in db.query(Game.id, Game.slug, Game.steam_appid).all():
        parsed = _trailing_digits(slug)
        if not parsed:
            continue
        suffix, length = parsed
        if length <= 2 and steam_appid == suffix:
            has_canonical = (
                db.query(Game.id)
                .filter(Game.slug.like(f"{slug}-%"))
                .first()
                is not None
            )
            short_suffix.append(
                {
                    "slug": slug,
                    "steam_appid": steam_appid,
                    "has_canonical": has_canonical,
                }
            )

    generic_covers = (
        db.query(func.count(Game.id))
        .filter(
            Game.steam_appid.isnot(None),
            Game.cover_image.isnot(None),
            Game.cover_image.like("%/header.jpg"),
            ~Game.cover_image.like("%/header.jpg?t=%"),
        )
        .scalar()
        or 0
    )

    return {
        "total_games": total,
        "steam_enriched": enriched,
        "not_enriched": not_enriched,
        "zero_offers": zero_offers,
        "generic_header_covers": generic_covers,
        "mistaken_stub_slugs": mistaken_stubs,
        "short_suffix_appid_matches": short_suffix[:30],
        "short_suffix_count": len(short_suffix),
    }
