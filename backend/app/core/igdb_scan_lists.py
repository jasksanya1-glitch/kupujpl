"""IGDB ranking lists → production Game rows + independent scanner priority."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import BASE_DIR
from app.core.igdb_api import IgdbClient, credentials_from_env
from app.core.steam_media import steam_cover_url
from app.models.models import Game, Offer

logger = logging.getLogger("igdb_scan_lists")

LISTS_CACHE = Path(BASE_DIR) / "tmp" / "igdb_scan_lists.json"
CACHE_MAX_AGE_HOURS = float(os.environ.get("IGDB_SCAN_LISTS_MAX_AGE_HOURS", "8"))

RANK_TRENDING = "TRENDING"
RANK_POPULAR = "POPULAR"
RANK_NEW = "NEW_RELEASES"
RANK_UPCOMING = "UPCOMING"
ALL_LISTS = (RANK_TRENDING, RANK_POPULAR, RANK_NEW, RANK_UPCOMING)


def _write_production_enabled() -> bool:
    return os.environ.get("IGDB_DISCOVERY_WRITE_PRODUCTION", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def enqueue_scanners_enabled() -> bool:
    return os.environ.get("IGDB_DISCOVERY_ENQUEUE_SCANNERS", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _top_n() -> int:
    return max(10, min(100, int(os.environ.get("IGDB_SCAN_LISTS_TOP_N", "40"))))


def load_igdb_scan_lists_cache() -> dict | None:
    if not LISTS_CACHE.is_file():
        return None
    try:
        return json.loads(LISTS_CACHE.read_text(encoding="utf-8"))
    except Exception:
        return None


def igdb_scan_priority_rank_map() -> dict[int, int]:
    """Lower rank index = higher scan priority (for shop_scan_queue)."""
    data = load_igdb_scan_lists_cache()
    if not data:
        return {}
    rank_map: dict[int, int] = {}
    idx = 0
    for list_name in ALL_LISTS:
        for row in (data.get("lists") or {}).get(list_name) or []:
            gid = row.get("game_id")
            if gid is None:
                continue
            ig = int(gid)
            if ig not in rank_map:
                rank_map[ig] = idx
                idx += 1
    return rank_map


def igdb_scan_priority_game_ids() -> set[int]:
    data = load_igdb_scan_lists_cache()
    if not data:
        return set()
    ids = data.get("enqueued_game_ids") or []
    return {int(x) for x in ids if x is not None}


def lists_cache_needs_refresh() -> bool:
    if not credentials_from_env():
        return False
    if not LISTS_CACHE.is_file():
        return True
    age_h = (time.time() - LISTS_CACHE.stat().st_mtime) / 3600
    return age_h >= CACHE_MAX_AGE_HOURS


def _category_to_list(category: str) -> str | None:
    return {
        "trending": RANK_TRENDING,
        "popular": RANK_POPULAR,
        "new_releases": RANK_NEW,
        "upcoming": RANK_UPCOMING,
    }.get(category or "")


def _upsert_game_from_appid(db: Session, appid: int, title: str) -> Game | None:
    from app.parsers.steam_catalog import upsert_game_stub

    game = db.query(Game).filter(Game.steam_appid == appid).first()
    if game:
        return game
    if not _write_production_enabled():
        return None
    try:
        upsert_game_stub(db, appid, title, steam_cover_url(appid))
        db.commit()
    except Exception as exc:
        logger.warning("IGDB stub upsert failed appid=%s: %s", appid, exc)
        db.rollback()
        return None
    return db.query(Game).filter(Game.steam_appid == appid).first()


def _mark_offers_stale_for_scan(db: Session, game_ids: list[int]) -> int:
    if not game_ids or not enqueue_scanners_enabled():
        return 0
    try:
        n = (
            db.query(Offer)
            .filter(Offer.game_id.in_(game_ids))
            .update({Offer.last_verified_at: None}, synchronize_session=False)
        )
        db.commit()
        return int(n or 0)
    except Exception as exc:
        logger.warning("IGDB scan stale mark failed: %s", exc)
        db.rollback()
        return 0


def refresh_igdb_scan_lists(db: Session, *, top_n: int | None = None) -> dict[str, Any]:
    """Fetch IGDB rankings, resolve Steam, optional prod stubs + scanner priority."""
    if not credentials_from_env():
        logger.warning("IGDB scan lists skipped: missing IGDB_CLIENT_ID/SECRET")
        return {"skipped": True, "reason": "missing_credentials"}

    if not _write_production_enabled() and not enqueue_scanners_enabled():
        logger.warning(
            "IGDB scan lists skipped: set IGDB_DISCOVERY_WRITE_PRODUCTION and/or "
            "IGDB_DISCOVERY_ENQUEUE_SCANNERS"
        )
        return {"skipped": True, "reason": "flags_disabled"}

    top_n = top_n or _top_n()
    from tools.igdb_discovery import config as igdb_config
    from tools.igdb_discovery.popularity import collect_categorized
    from tools.igdb_discovery.steam_resolve import resolve_many
    from tools.igdb_discovery.steam_verify import SteamVerifier

    igdb_config.CATALOG_DB = Path(BASE_DIR) / "database.db"
    # Writable on VPS (www-data); avoid tools/igdb_discovery/staging permissions.
    igdb_config.STAGING_DIR = Path(BASE_DIR) / "tmp" / "igdb_staging"
    igdb_config.STAGING_DIR.mkdir(parents=True, exist_ok=True)
    from tools.igdb_discovery import pop_history

    pop_history.SNAP_DB = igdb_config.STAGING_DIR / "pop_score_history.sqlite3"

    client = IgdbClient()
    client.ensure_token()
    scored, fetch_stats = collect_categorized(client, per_category=top_n, pool=max(120, top_n * 4))

    catalog_steam_ids = {
        int(g.steam_appid)
        for g in db.query(Game.steam_appid).filter(Game.steam_appid.isnot(None)).all()
        if g.steam_appid
    }
    games = [(s.candidate.igdb_id, s.candidate.name) for s in scored]
    verifier = SteamVerifier()
    resolutions = resolve_many(client, games, verifier, catalog_steam_ids=catalog_steam_ids)

    lists: dict[str, list[dict[str, Any]]] = {k: [] for k in ALL_LISTS}
    seen_appids: set[int] = set()
    enqueued_ids: list[int] = []

    for scored in scored:
        cand = scored.candidate
        list_name = _category_to_list(scored.category)
        if not list_name:
            continue
        if len(lists[list_name]) >= top_n:
            continue
        res = resolutions.get(cand.igdb_id)
        if not res or res.status != "verified" or not res.appid:
            continue
        appid = int(res.appid)
        if appid in seen_appids:
            continue
        seen_appids.add(appid)

        game = db.query(Game).filter(Game.steam_appid == appid).first()
        if not game:
            game = _upsert_game_from_appid(db, appid, cand.name)
        if not game:
            continue

        row = {
            "rank": len(lists[list_name]) + 1,
            "igdb_id": cand.igdb_id,
            "name": cand.name,
            "steam_appid": appid,
            "game_id": game.id,
            "slug": game.slug,
            "in_quenly": True,
        }
        lists[list_name].append(row)
        enqueued_ids.append(game.id)

    offers_marked = 0
    if enqueue_scanners_enabled() and enqueued_ids:
        offers_marked = _mark_offers_stale_for_scan(db, list(dict.fromkeys(enqueued_ids)))

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "top_n": top_n,
        "lists": lists,
        "enqueued_game_ids": list(dict.fromkeys(enqueued_ids)),
        "enqueued_count": len(set(enqueued_ids)),
        "offers_marked_stale": offers_marked,
        "write_production": _write_production_enabled(),
        "enqueue_scanners": enqueue_scanners_enabled(),
        "fetch_stats": fetch_stats,
        "counts": {k: len(v) for k, v in lists.items()},
    }
    LISTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    LISTS_CACHE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "IGDB scan lists refreshed: enqueued=%s offers_stale=%s",
        payload["enqueued_count"],
        offers_marked,
    )
    return {
        "updated_at": payload["updated_at"],
        "counts": payload["counts"],
        "enqueued_count": payload["enqueued_count"],
        "offers_marked_stale": offers_marked,
    }
