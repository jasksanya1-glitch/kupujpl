"""Top-5000 Steam top sellers list for daily Tier A scan."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.core.database import BASE_DIR, SessionLocal
from app.models.models import Game

logger = logging.getLogger("tier_a_top5000")

TIER_A_SIZE = int(os.environ.get("TIER_A_SIZE", "5000"))
TIER_A_DAILY_HOUR = int(os.environ.get("TIER_A_DAILY_HOUR", "2"))
TIER_A_DAILY_MINUTE = int(os.environ.get("TIER_A_DAILY_MINUTE", "30"))
TIER_A_STEAM_APP_TYPES = tuple(
    t.strip().lower()
    for t in os.environ.get("TIER_A_STEAM_APP_TYPES", "game,dlc").split(",")
    if t.strip()
) or ("game", "dlc")
TIER_A_SYNC_DLCS = os.environ.get("TIER_A_SYNC_DLCS", "1").lower() in ("1", "true", "yes")
TIER_A_SYNC_DLC_PARENTS = int(os.environ.get("TIER_A_SYNC_DLC_PARENTS", "800"))
TIER_A_MAX_NEW_DLCS = int(os.environ.get("TIER_A_MAX_NEW_DLCS", "2000"))
TIER_A_DLC_REQUEST_DELAY = float(os.environ.get("TIER_A_DLC_REQUEST_DELAY", "0.35"))
TIER_A_DLC_SKIP_IF_CACHE_HOURS = float(os.environ.get("TIER_A_DLC_SKIP_IF_CACHE_HOURS", "12"))
TIER_A_TOP_SELLERS_PAGE_SIZE = max(1, min(100, int(os.environ.get("TIER_A_TOP_SELLERS_PAGE_SIZE", "50"))))
TIER_A_TOP_SELLERS_DELAY = float(os.environ.get("TIER_A_TOP_SELLERS_DELAY", "0.35"))
CACHE_PATH = Path(BASE_DIR) / "tmp" / "tier_a_top5000.json"

_appid_set: frozenset[int] | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_tier_a_scan_at() -> str:
    """Next daily scan at TIER_A_DAILY_HOUR (Europe/Warsaw approx via local server TZ)."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(os.environ.get("TIER_A_TZ", "Europe/Warsaw"))
        now = datetime.now(tz)
        target = now.replace(
            hour=TIER_A_DAILY_HOUR,
            minute=TIER_A_DAILY_MINUTE,
            second=0,
            microsecond=0,
        )
        if now >= target:
            target += timedelta(days=1)
        return target.isoformat()
    except Exception:
        now = _utcnow()
        target = now.replace(hour=TIER_A_DAILY_HOUR, minute=TIER_A_DAILY_MINUTE, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        return target.isoformat() + "+00:00"


def _tier_a_parent_types() -> tuple[str, ...]:
    return tuple(t for t in TIER_A_STEAM_APP_TYPES if t != "dlc") or ("game",)


def _cache_rebuilt_hours_ago() -> float | None:
    if not CACHE_PATH.is_file():
        return None
    try:
        cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        rebuilt = cache.get("rebuilt_at")
        if not rebuilt:
            return None
        ts = datetime.fromisoformat(str(rebuilt).replace("Z", ""))
        return max(0.0, (_utcnow() - ts).total_seconds() / 3600.0)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def _should_skip_dlc_sync() -> bool:
    """Skip slow Steam DLC import when tier-A cache was rebuilt recently."""
    if not TIER_A_SYNC_DLCS:
        return True
    age_h = _cache_rebuilt_hours_ago()
    if age_h is None:
        return False
    if age_h < TIER_A_DLC_SKIP_IF_CACHE_HOURS:
        logger.info(
            "Skipping DLC sync — cache rebuilt %.1fh ago (< %.0fh)",
            age_h,
            TIER_A_DLC_SKIP_IF_CACHE_HOURS,
        )
        return True
    return False


def _dlc_sync_progress(added: int, *, parent_title: str | None = None, parents_done: int = 0, parents_total: int = 0) -> None:
    try:
        from app.parsers.tier_a_scan_state import save_vps_state

        patch: dict[str, Any] = {
            "phase": "rebuild_list",
            "games_done": added,
            "games_total": TIER_A_MAX_NEW_DLCS,
            "progress_pct": round(min(100.0, added / max(TIER_A_MAX_NEW_DLCS, 1) * 100), 1),
            "scan_subphase": f"DLC sync {added}/{TIER_A_MAX_NEW_DLCS}",
        }
        if parent_title:
            patch["current_game"] = parent_title
        if parents_total:
            patch["scan_subphase"] = (
                f"DLC {added}/{TIER_A_MAX_NEW_DLCS} · батьки {parents_done}/{parents_total}"
            )
        save_vps_state(patch)
    except Exception as exc:
        logger.debug("DLC progress state update failed: %s", exc)


def _tier_a_scan_games_query(db: Session):
    """Tier A fallback pool: popular games + DLC (no catalog visibility / offer requirements)."""
    parent_types = _tier_a_parent_types()
    return (
        db.query(Game)
        .filter(Game.steam_enriched == True)
        .filter(Game.steam_appid.isnot(None))
        .filter(Game.is_free.isnot(True))
        .filter(Game.is_coming_soon.isnot(True))
        .filter(
            or_(
                Game.steam_app_type.is_(None),
                Game.steam_app_type.in_(list(TIER_A_STEAM_APP_TYPES)),
            )
        )
        .order_by(
            Game.steam_review_count.desc().nulls_last(),
            Game.steam_recommendations.desc().nulls_last(),
        )
    )


def _fetch_steam_top_seller_items(*, limit: int) -> tuple[list[dict[str, Any]], int | None]:
    """Fetch Steam Store Top Sellers in rank order.

    Steam does not publish purchase counts. The public topsellers search list is
    the closest stable proxy available in the existing Steam Store JSON flow.
    """
    from app.parsers.steam_lists import fetch_steam_search_page

    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    total_count: int | None = None
    start = 0

    while len(items) < limit:
        batch, total = fetch_steam_search_page(
            start=start,
            count=min(TIER_A_TOP_SELLERS_PAGE_SIZE, limit - len(items)),
            filter_name="topsellers",
            category1="998",
            hidef2p=1,
        )
        if total_count is None and total is not None:
            total_count = total
        if not batch:
            break
        for item in batch:
            appid = item.get("appid")
            if appid and appid not in seen:
                seen.add(appid)
                items.append(item)
                if len(items) >= limit:
                    break
        if len(batch) < TIER_A_TOP_SELLERS_PAGE_SIZE:
            break
        start += TIER_A_TOP_SELLERS_PAGE_SIZE
        time.sleep(TIER_A_TOP_SELLERS_DELAY)

    return items, total_count


def _sync_steam_top_seller_stubs(db: Session, items: list[dict[str, Any]]) -> None:
    """Persist Steam list appids without triggering per-game price scans."""
    from app.core.db_retry import commit_with_retry
    from app.core.steam_media import steam_cover_url
    from app.parsers.steam_catalog import upsert_game_stub

    for item in items:
        appid = item.get("appid")
        if not appid:
            continue
        try:
            upsert_game_stub(
                db,
                int(appid),
                item.get("title") or f"Steam {appid}",
                item.get("cover_image") or steam_cover_url(int(appid)),
            )
        except Exception as exc:
            logger.debug("Tier A top seller stub skip %s: %s", appid, exc)
            db.rollback()
    commit_with_retry(db)


def _tier_a_game_allowed(game: Game) -> bool:
    if not game.steam_appid:
        return False
    if game.is_free is True or game.is_coming_soon is True:
        return False
    app_type = (game.steam_app_type or "").strip().lower()
    return not app_type or app_type in TIER_A_STEAM_APP_TYPES


def _games_by_appid(db: Session, appids: list[int]) -> dict[int, Game]:
    games: dict[int, Game] = {}
    for start in range(0, len(appids), 800):
        chunk = appids[start : start + 800]
        if not chunk:
            continue
        for game in db.query(Game).filter(Game.steam_appid.in_(chunk)).all():
            if game.steam_appid is not None:
                games[int(game.steam_appid)] = game
    return games


def _cache_item(game: Game, *, rank: int, source: str, source_rank: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "game_id": game.id,
        "steam_appid": game.steam_appid,
        "slug": game.slug,
        "title": game.title,
        "steam_app_type": game.steam_app_type,
        "tier_a_rank": rank,
        "tier_a_source": source,
    }
    if source_rank is not None:
        item["steam_top_sellers_rank"] = source_rank
    return item


def sync_tier_a_dlcs(db: Session) -> int:
    """Import DLC appids from top base games (Steam appdetails ``dlc`` list)."""
    if not TIER_A_SYNC_DLCS or "dlc" not in TIER_A_STEAM_APP_TYPES:
        return 0

    from app.core.db_retry import commit_with_retry
    from app.parsers.steam_catalog import enrich_game, fetch_appdetails, upsert_game_stub
    from app.parsers.tier_a_scan_state import is_vps_cancel_requested

    parents = (
        db.query(Game)
        .filter(Game.steam_enriched == True)
        .filter(Game.steam_appid.isnot(None))
        .filter(
            or_(Game.steam_app_type.is_(None), Game.steam_app_type.in_(list(_tier_a_parent_types())))
        )
        .order_by(Game.steam_review_count.desc().nulls_last())
        .limit(TIER_A_SYNC_DLC_PARENTS)
        .all()
    )

    added = 0
    seen: set[int] = set()
    parents_total = len(parents)
    _dlc_sync_progress(0, parents_done=0, parents_total=parents_total)
    for parent_idx, parent in enumerate(parents, start=1):
        if is_vps_cancel_requested():
            logger.info("Tier A DLC sync cancelled at %s new", added)
            return added
        if not parent.steam_appid:
            continue
        parent_data = fetch_appdetails(parent.steam_appid)
        time.sleep(TIER_A_DLC_REQUEST_DELAY)
        if not parent_data:
            continue
        for raw_id in parent_data.get("dlc") or []:
            if is_vps_cancel_requested():
                return added
            try:
                dlc_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if dlc_id in seen:
                continue
            seen.add(dlc_id)

            existing = db.query(Game).filter(Game.steam_appid == dlc_id).first()
            if existing:
                if not existing.steam_enriched:
                    enrich_game(db, existing)
                    commit_with_retry(db)
                continue

            dlc_data = fetch_appdetails(dlc_id)
            time.sleep(TIER_A_DLC_REQUEST_DELAY)
            if not dlc_data:
                continue
            if (dlc_data.get("type") or "").lower() != "dlc":
                continue
            game = upsert_game_stub(
                db,
                dlc_id,
                dlc_data.get("name") or f"DLC {dlc_id}",
                dlc_data.get("header_image"),
            )
            enrich_game(db, game)
            commit_with_retry(db)
            added += 1
            if added % 25 == 0:
                logger.info(
                    "Tier A DLC sync progress: %s new (parents scanned so far: %s)",
                    added,
                    parent_idx,
                )
                _dlc_sync_progress(
                    added,
                    parent_title=parent.title,
                    parents_done=parent_idx,
                    parents_total=parents_total,
                )
            if added >= TIER_A_MAX_NEW_DLCS:
                logger.info("Tier A DLC sync cap reached (%s)", TIER_A_MAX_NEW_DLCS)
                return added

        if parent_idx % 20 == 0:
            _dlc_sync_progress(
                added,
                parent_title=parent.title,
                parents_done=parent_idx,
                parents_total=parents_total,
            )

    logger.info("Tier A DLC sync: %s new DLC rows from %s parents", added, len(parents))
    return added


def rebuild_tier_a_cache(db: Session | None = None) -> dict[str, Any]:
    """Rebuild top-N list ordered by Steam Top Sellers rank."""
    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        if _should_skip_dlc_sync():
            pass
        else:
            sync_tier_a_dlcs(db)
        top_seller_items, steam_total_count = _fetch_steam_top_seller_items(limit=TIER_A_SIZE)
        _sync_steam_top_seller_stubs(db, top_seller_items)

        ranked_appids = [int(i["appid"]) for i in top_seller_items if i.get("appid")]
        games_by_appid = _games_by_appid(db, ranked_appids)
        items: list[dict[str, Any]] = []
        used_appids: set[int] = set()

        for source_rank, appid in enumerate(ranked_appids, start=1):
            game = games_by_appid.get(appid)
            if not game or not _tier_a_game_allowed(game):
                continue
            used_appids.add(appid)
            items.append(
                _cache_item(
                    game,
                    rank=len(items) + 1,
                    source="steam_top_sellers",
                    source_rank=source_rank,
                )
            )
            if len(items) >= TIER_A_SIZE:
                break

        fallback_count = 0
        if len(items) < TIER_A_SIZE:
            for game in _tier_a_scan_games_query(db).limit(TIER_A_SIZE * 2).all():
                appid = int(game.steam_appid) if game.steam_appid is not None else None
                if appid is None or appid in used_appids:
                    continue
                items.append(
                    _cache_item(
                        game,
                        rank=len(items) + 1,
                        source="db_popularity_fallback",
                    )
                )
                used_appids.add(appid)
                fallback_count += 1
                if len(items) >= TIER_A_SIZE:
                    break

        payload: dict[str, Any] = {
            "version": _utcnow().strftime("%Y-%m-%dT%H"),
            "rebuilt_at": _utcnow().isoformat() + "Z",
            "count": len(items),
            "list_ready": True,
            "source": "steam_top_sellers",
            "source_slug": "topsellers",
            "source_label": "Steam Top Sellers",
            "source_note": (
                "Steam does not publish purchase counts; this list uses the public "
                "Steam Store topsellers ranking as the closest available proxy."
            ),
            "ranking_basis": "steam_store_topsellers",
            "steam_filter": "topsellers",
            "steam_category1": "998",
            "steam_hidef2p": True,
            "steam_top_sellers_fetched": len(top_seller_items),
            "steam_top_sellers_total_count": steam_total_count,
            "fallback_source": "db_popularity_fallback",
            "fallback_count": fallback_count,
            "app_types": list(TIER_A_STEAM_APP_TYPES),
            "appids": [i["steam_appid"] for i in items if i["steam_appid"]],
            "games": items,
        }
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        global _appid_set
        _appid_set = frozenset(payload["appids"])
        logger.info("Tier A cache rebuilt: %s games", len(items))
        return payload
    finally:
        if own_db and db is not None:
            db.close()


def load_tier_a_cache() -> dict[str, Any]:
    if not CACHE_PATH.is_file():
        return {"list_ready": False, "games": [], "appids": [], "count": 0}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"list_ready": False, "games": [], "appids": [], "count": 0}


def load_tier_a_appid_set() -> frozenset[int]:
    global _appid_set
    if _appid_set is not None:
        return _appid_set
    cache = load_tier_a_cache()
    appids = cache.get("appids") or []
    _appid_set = frozenset(int(a) for a in appids if a is not None)
    return _appid_set


def is_in_tier_a_daily_scan(game: Game | None) -> bool:
    if not game or not game.steam_appid:
        return False
    return int(game.steam_appid) in load_tier_a_appid_set()


def is_tier_a_appid(appid: int | None) -> bool:
    if appid is None:
        return False
    return int(appid) in load_tier_a_appid_set()


def append_games_to_tier_a_cache(
    db: Session,
    games: list[Game],
    *,
    source: str = "steam_wishlist",
) -> list[int]:
    """Append games to Tier A scan cache when missing. Returns newly added appids."""
    if not games:
        return []

    cache = load_tier_a_cache()
    if not cache.get("list_ready"):
        cache = {
            "list_ready": True,
            "version": cache.get("version") or 1,
            "games": [],
            "appids": [],
            "count": 0,
        }

    appid_set = {int(a) for a in (cache.get("appids") or []) if a is not None}
    games_list = list(cache.get("games") or [])
    added_appids: list[int] = []

    for game in games:
        if not game or not game.steam_appid:
            continue
        appid = int(game.steam_appid)
        if appid in appid_set:
            continue
        if not game.id:
            db.refresh(game)
        if not _tier_a_game_allowed(game):
            continue
        appid_set.add(appid)
        games_list.append(_cache_item(game, rank=len(games_list) + 1, source=source))
        added_appids.append(appid)

    if not added_appids:
        return []

    cache["games"] = games_list
    cache["appids"] = [int(g["steam_appid"]) for g in games_list if g.get("steam_appid")]
    cache["count"] = len(games_list)
    cache["rebuilt_at"] = cache.get("rebuilt_at") or _utcnow().isoformat() + "Z"
    meta = cache.setdefault("extra_sources", {})
    meta[source] = int(meta.get(source, 0)) + len(added_appids)

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    global _appid_set
    _appid_set = frozenset(cache["appids"])
    logger.info("Tier A cache appended %s games from %s", len(added_appids), source)
    return added_appids


def build_tier_a_queue(db: Session, *, limit: int = 5000) -> list[dict[str, Any]]:
    """Queue tier-A games for local workers — built from cache (no heavy DB join)."""
    cache = load_tier_a_cache()
    if not cache.get("list_ready"):
        return []

    out: list[dict[str, Any]] = []
    for g in (cache.get("games") or [])[:limit]:
        gid = g.get("game_id")
        if not gid:
            continue
        out.append(
            {
                "game_id": gid,
                "title": g.get("title"),
                "slug": g.get("slug"),
                "steam_appid": g.get("steam_appid"),
                "tier_a_rank": g.get("tier_a_rank"),
                "tier_a_source": g.get("tier_a_source"),
                "steam_top_sellers_rank": g.get("steam_top_sellers_rank"),
                "shop_count": 0,
                "present_shops": [],
                "missing_shops": [],
            }
        )
    return out
