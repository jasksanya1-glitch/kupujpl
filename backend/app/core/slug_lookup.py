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


_DLC_SLUG_MARKERS = (
    "-dlc-",
    "-season-pass",
    "-soundtrack",
    "-ost-",
    "-deluxe-pack",
    "-voidfarer-pack",
    "-appearance-pack",
    "-cosmetic",
    "-bundle-",
)
_DLC_TITLE_MARKERS = (
    " dlc",
    "season pass",
    "soundtrack",
    " deluxe pack",
    " voidfarer pack",
    " appearance pack",
    " bundle",
)


def _looks_like_dlc_or_addon(game: Game) -> bool:
    """Heuristic: extended-slug DLC/packs must not win over the base game."""
    slug = f"-{(game.slug or '').lower()}-"
    title = f" {(game.title or '').lower()} "
    if any(m in slug for m in _DLC_SLUG_MARKERS):
        return True
    if any(m in title for m in _DLC_TITLE_MARKERS):
        return True
    # "Title - Subtitle" Steam DLC naming (base titles rarely use " - ").
    if " - " in (game.title or ""):
        return True
    return False


def _pick_best_game(candidates: list[Game]) -> Game:
    """Prefer the main/base catalog title when a short slug matches a family.

    Never prefer higher Steam appids — DLC/packs often have newer/higher IDs
    (e.g. Rogue Trader Voidfarer Pack beating the base game).
    """
    return max(
        candidates,
        key=lambda g: (
            bool(g.steam_enriched),
            0 if _looks_like_dlc_or_addon(g) else 1,
            int(getattr(g, "steam_review_count", None) or 0),
            int(getattr(g, "steam_recommendations", None) or 0),
            len(g.offers),
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
