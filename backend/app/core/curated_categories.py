"""Virtual catalog filters backed by Steam Store lists."""
from __future__ import annotations

from app.parsers.steam_lists import is_steam_list_slug

CURATED_CATEGORIES: dict[str, dict[str, str]] = {
    "nowe-gry": {
        "name": "Nowe gry",
        "label": "🆕 Nowe gry",
    },
    "top-sprzedaz": {
        "name": "Top sprzedaż",
        "label": "🏆 Top sprzedaż",
    },
}


def is_curated_slug(slug: str | None) -> bool:
    if not slug:
        return False
    return slug.strip().lower() in CURATED_CATEGORIES


def curated_display_name(slug: str) -> str:
    meta = CURATED_CATEGORIES.get(slug.strip().lower())
    return meta["name"] if meta else slug


def uses_steam_list(slug: str | None) -> bool:
    """True when category should be loaded from Steam Store search."""
    if not slug:
        return False
    key = slug.strip().lower()
    return is_curated_slug(key) or is_steam_list_slug(key)
