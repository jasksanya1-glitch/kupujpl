"""Add PlayStation / Xbox titles to favorites and queue keyshop scan."""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.db_retry import commit_with_retry
from app.models.models import Favorite, Game
from app.parsers.keyshop_common import slugify

logger = logging.getLogger("console_game_import")

_PLATFORM_LABEL = {"ps": "PlayStation", "xbox": "Xbox"}


def _normalize_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", (title or "").strip())
    return cleaned


def _unique_console_slug(db: Session, platform: str, title: str) -> str:
    base = slugify(f"{platform}-{title}") or f"{platform}-game"
    base = base[:200]
    candidate = base
    n = 2
    while db.query(Game.id).filter(Game.slug == candidate).first():
        candidate = f"{base}-{n}"[:255]
        n += 1
    return candidate


def add_console_game_to_scan(
    db: Session,
    *,
    user_id: int,
    title: str,
    platform: str,
) -> dict[str, Any]:
    platform = (platform or "").strip().lower()
    if platform not in ("ps", "xbox"):
        raise ValueError("Platforma musi być ps lub xbox.")

    title = _normalize_title(title)
    if len(title) < 2:
        raise ValueError("Podaj nazwę gry (min. 2 znaki).")

    # Reuse existing console stub with same platform + similar title (case-insensitive).
    existing = (
        db.query(Game)
        .filter(Game.platform == platform, Game.steam_appid.is_(None))
        .filter(Game.title.ilike(title))
        .first()
    )

    created_catalog = False
    if existing:
        game = existing
    else:
        game = Game(
            title=title,
            slug=_unique_console_slug(db, platform, title),
            platform=platform,
            steam_appid=None,
            steam_enriched=True,  # skip Steam enrich attempts
            description=f"Tytuł konsolowy ({_PLATFORM_LABEL.get(platform, platform)}) dodany z panelu użytkownika.",
        )
        db.add(game)
        commit_with_retry(db)
        db.refresh(game)
        created_catalog = True
        logger.info("Created console game id=%s slug=%s platform=%s", game.id, game.slug, platform)

    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == user_id, Favorite.game_id == game.id)
        .first()
    )
    already_tracked = fav is not None
    if not fav:
        fav = Favorite(user_id=user_id, game_id=game.id, alert_enabled=True)
        db.add(fav)
        commit_with_retry(db)

    label = _PLATFORM_LABEL.get(platform, platform)
    if already_tracked:
        message = (
            f"„{title}” ({label}) jest już na Twojej liście śledzenia — "
            "odświeżamy ceny w sklepach z kluczami."
        )
    elif created_catalog:
        message = (
            f"Dodano „{title}” ({label}) do śledzenia i kolejki skanu cen "
            "(Instant Gaming i inne keyshopy z ofertami konsolowymi)."
        )
    else:
        message = (
            f"Dodano „{title}” ({label}) do śledzenia — skan cen uruchomiony w tle."
        )

    return {
        "ok": True,
        "game_id": game.id,
        "slug": game.slug,
        "title": game.title,
        "platform": platform,
        "already_tracked": already_tracked,
        "created_catalog": created_catalog,
        "scan_queued": True,
        "message": message,
    }
