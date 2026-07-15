"""Resolve game slugs safely — avoid treating title numbers (CS2, FH6) as Steam appids."""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models.models import Game

_SLUG_APPID_RE = re.compile(r"-(\d+)$")


def _trailing_digits(slug: str) -> tuple[int, int] | None:
    m = _SLUG_APPID_RE.search(slug)
    if not m:
        return None
    digits = m.group(1)
    return int(digits), len(digits)


def _steam_appid_from_slug_suffix(slug: str) -> int | None:
    """Parse Steam appid from slug suffix; reject 1–2 digit title numbers (GTA 5, CS 2)."""
    parsed = _trailing_digits(slug)
    if not parsed:
        return None
    appid, length = parsed
    if length <= 2:
        return None
    return appid


def _likely_mistaken_stub(game: Game, slug: str) -> bool:
    parsed = _trailing_digits(slug)
    if not parsed:
        return False
    suffix, length = parsed
    if length > 2:
        return False
    if game.steam_appid != suffix:
        return False
    return not game.steam_enriched or len(game.offers) == 0


def _pick_best_game(candidates: list[Game]) -> Game:
    return max(
        candidates,
        key=lambda g: (
            bool(g.steam_enriched),
            len(g.offers),
            g.steam_appid or 0,
            g.id,
        ),
    )


def _extended_slug_matches(db: Session, slug: str) -> list[Game]:
    return (
        db.query(Game)
        .filter(Game.slug.like(f"{slug}-%"))
        .all()
    )


def resolve_game_slug(db: Session, slug: str) -> Game | None:
    """Find the best game record for a URL slug."""
    slug = (slug or "").strip().lower()
    if not slug:
        return None

    exact = db.query(Game).filter(Game.slug == slug).first()
    extended = _extended_slug_matches(db, slug)

    if extended:
        if exact is None:
            return _pick_best_game(extended)
        if _likely_mistaken_stub(exact, slug):
            return _pick_best_game([exact, *extended])
        return exact

    if exact:
        return exact

    appid = _steam_appid_from_slug_suffix(slug)
    if appid is not None:
        return db.query(Game).filter(Game.steam_appid == appid).first()

    return None
