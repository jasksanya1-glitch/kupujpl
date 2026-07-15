"""Prefetch offers for homepage / featured Steam list games (2x daily cron)."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, joinedload

from app.core.database import BASE_DIR, SessionLocal
from app.models.models import Game
from app.parsers.game_offers import refresh_offers_for_game
from app.parsers.home_featured import CACHE_FILE, HOME_SECTIONS, _load_cache
from app.parsers.steam_lists import get_steam_list_items

logger = logging.getLogger("featured_offer_prefetch")

GAME_DELAY_SEC = float(os.environ.get("OFFER_REFRESH_GAME_DELAY_SEC", "0.8"))
PREFETCH_PER_SECTION = int(os.environ.get("FEATURED_PREFETCH_PER_SECTION", "12"))


def _appids_from_home_cache() -> set[int]:
    appids: set[int] = set()
    cache = _load_cache()
    if not cache:
        return appids
    for section in cache.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for item in section.get("games") or []:
            if not isinstance(item, dict):
                continue
            aid = item.get("appid")
            if aid:
                appids.add(int(aid))
    return appids


def _appids_from_steam_lists() -> set[int]:
    appids: set[int] = set()
    slugs = {s.get("steam_slug") or s["slug"] for s in HOME_SECTIONS}
    for slug in slugs:
        try:
            items, _total = get_steam_list_items(slug)
        except Exception as exc:
            logger.warning("Steam list %s failed: %s", slug, exc)
            continue
        for item in (items or [])[:PREFETCH_PER_SECTION]:
            if not isinstance(item, dict):
                continue
            aid = item.get("appid")
            if aid:
                appids.add(int(aid))
    return appids


def collect_featured_appids() -> list[int]:
    combined = _appids_from_home_cache() | _appids_from_steam_lists()
    return sorted(combined)


def select_featured_games(db: Session) -> list[Game]:
    appids = collect_featured_appids()
    if not appids:
        return []
    return (
        db.query(Game)
        .options(joinedload(Game.offers))
        .filter(Game.steam_appid.in_(appids), Game.steam_enriched == True)
        .all()
    )


def run_featured_offer_prefetch(*, force: bool = False) -> dict[str, Any]:
    started = time.time()
    db = SessionLocal()
    stats: dict[str, Any] = {
        "featured_appids": 0,
        "games_selected": 0,
        "games_refreshed": 0,
        "errors": 0,
    }
    try:
        appids = collect_featured_appids()
        stats["featured_appids"] = len(appids)
        games = select_featured_games(db)
        stats["games_selected"] = len(games)
    finally:
        db.close()

    for game in games:
        try:
            refresh_offers_for_game(game.id, force=force, fill_missing=True)
            stats["games_refreshed"] += 1
        except Exception as exc:
            logger.warning("Prefetch failed for %s: %s", game.id, exc)
            stats["errors"] += 1
        time.sleep(GAME_DELAY_SEC)

    stats["duration_sec"] = round(time.time() - started, 1)
    state_path = BASE_DIR / "tmp" / "featured_prefetch_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "Featured prefetch done: %s/%s games in %ss",
        stats["games_refreshed"],
        stats["games_selected"],
        stats["duration_sec"],
    )
    return stats


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    run_featured_offer_prefetch()


if __name__ == "__main__":
    main()
