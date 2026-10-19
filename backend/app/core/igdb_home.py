"""IGDB PopScore sections for Quenly homepage (TRENDING / POPULAR on PC)."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.igdb_api import IgdbClient, credentials_from_env
from app.core.steam_media import steam_cover_url
from app.models.models import Game
from app.parsers.home_featured import _enrich_cache_items, _upsert_section_games

logger = logging.getLogger("igdb_home")

CACHE_FILE = Path(__file__).resolve().parents[2] / "tmp" / "igdb_home_cache.json"
CACHE_MAX_AGE_HOURS = 8

POP_WANT_TO_PLAY = 2
POP_GLOBAL_TOP_SELLERS = 9

IGDB_HOME_SECTIONS = [
    {
        "slug": "igdb-trending",
        "catalog_slug": "igdb-trending",
        "name": "🔥 Trending (IGDB)",
        "subtitle": "Rosnące zainteresowanie na PC (IGDB PopScore, źródło: Twitch/IGDB)",
        "igdb_list": "trending",
    },
    {
        "slug": "igdb-popular",
        "catalog_slug": "igdb-popular",
        "name": "⭐ Popularne (IGDB)",
        "subtitle": "Globalni bestsellerzy PC (IGDB PopScore)",
        "igdb_list": "popular",
    },
]


def _chunked(ids: list[int], size: int = 50) -> list[list[int]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def _fetch_pop_pairs(client: IgdbClient, popularity_type: int, *, limit: int) -> list[tuple[int, float]]:
    body = (
        f"fields game_id,value,popularity_type;"
        f" sort value desc; limit {int(limit)};"
        f" where popularity_type = {int(popularity_type)};"
    )
    rows = client.query("popularity_primitives", body)
    out: list[tuple[int, float]] = []
    for row in rows:
        gid = row.get("game_id")
        if gid is None:
            continue
        out.append((int(gid), float(row.get("value") or 0.0)))
    return out


def _hydrate_games(client: IgdbClient, game_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not game_ids:
        return {}
    rows: list[dict[str, Any]] = []
    for chunk in _chunked(game_ids, 50):
        id_list = ",".join(str(i) for i in chunk)
        body = (
            "fields id,name,slug,game_type,category,first_release_date,platforms,"
            "parent_game,version_parent,summary;"
            f" where id = ({id_list});"
            f" limit {len(chunk)};"
        )
        rows.extend(client.query("games", body))
    return {int(r["id"]): r for r in rows if r.get("id") is not None}


def _is_pc_mainline(raw: dict[str, Any]) -> bool:
    from tools.igdb_discovery.fetchers import is_pc_mainline

    ok, _ = is_pc_mainline(raw)
    return ok


def _resolve_steam_appids(
    client: IgdbClient,
    games: list[tuple[int, str]],
    catalog_steam_ids: set[int],
) -> dict[int, int | None]:
    from tools.igdb_discovery.steam_resolve import resolve_many
    from tools.igdb_discovery.steam_verify import SteamVerifier

    if not games:
        return {}
    # Production home: reuse discovery-grade resolver (no lowest-AppID guessing).
    verifier = SteamVerifier(pause_sec=0.12)
    resolutions = resolve_many(client, games, verifier, catalog_steam_ids=catalog_steam_ids)
    out: dict[int, int | None] = {}
    for gid, res in resolutions.items():
        out[gid] = res.appid if res.status == "verified" else None
    return out


def _pick_pc_appids(
    client: IgdbClient,
    pairs: list[tuple[int, float]],
    *,
    limit: int,
    catalog_steam_ids: set[int],
    used_appids: set[int],
) -> list[dict[str, Any]]:
    ids = [gid for gid, _ in pairs]
    hydrated = _hydrate_games(client, ids)
    candidates: list[tuple[int, str]] = []
    for gid, _ in pairs:
        raw = hydrated.get(gid)
        if not raw or not _is_pc_mainline(raw):
            continue
        candidates.append((gid, str(raw.get("name") or f"igdb-{gid}")))
        if len(candidates) >= limit * 4:
            break

    steam_map = _resolve_steam_appids(client, candidates, catalog_steam_ids)
    items: list[dict[str, Any]] = []
    for gid, _ in pairs:
        raw = hydrated.get(gid)
        if not raw or not _is_pc_mainline(raw):
            continue
        appid = steam_map.get(gid)
        if not appid or appid in used_appids:
            continue
        used_appids.add(appid)
        items.append(
            {
                "appid": appid,
                "title": str(raw.get("name") or f"Gra {appid}"),
                "cover_image": steam_cover_url(appid),
                "igdb_id": gid,
            }
        )
        if len(items) >= limit:
            break
    return items


def refresh_igdb_home_cache(db: Session, *, games_per_section: int = 12) -> dict[str, Any]:
    if not credentials_from_env():
        logger.warning("IGDB home refresh skipped: IGDB_CLIENT_ID/SECRET not configured")
        return {"skipped": True, "reason": "missing_credentials"}

    client = IgdbClient()
    client.ensure_token()

    pool = max(80, games_per_section * 8)
    want = _fetch_pop_pairs(client, POP_WANT_TO_PLAY, limit=pool)
    sellers = _fetch_pop_pairs(client, POP_GLOBAL_TOP_SELLERS, limit=pool)

    catalog_steam_ids = {
        int(g.steam_appid)
        for g in db.query(Game.steam_appid).filter(Game.steam_appid.isnot(None)).all()
        if g.steam_appid
    }

    used_appids: set[int] = set()
    sections_data: list[dict[str, Any]] = []

    trending_items = _pick_pc_appids(
        client,
        want,
        limit=games_per_section,
        catalog_steam_ids=catalog_steam_ids,
        used_appids=used_appids,
    )
    if trending_items:
        _upsert_section_games(db, trending_items)
        try:
            db.commit()
        except Exception:
            db.rollback()
        trending_items = _enrich_cache_items(db, trending_items)
        trend_meta = IGDB_HOME_SECTIONS[0]
        sections_data.append(
            {
                "slug": trend_meta["slug"],
                "catalog_slug": trend_meta["catalog_slug"],
                "name": trend_meta["name"],
                "subtitle": trend_meta["subtitle"],
                "games": trending_items,
            }
        )

    pop_meta = IGDB_HOME_SECTIONS[1]
    popular_pairs = sellers if sellers else want
    popular_items = _pick_pc_appids(
        client,
        popular_pairs,
        limit=games_per_section,
        catalog_steam_ids=catalog_steam_ids,
        used_appids=used_appids,
    )
    if popular_items:
        _upsert_section_games(db, popular_items)
        try:
            db.commit()
        except Exception:
            db.rollback()
        popular_items = _enrich_cache_items(db, popular_items)
        pop_subtitle = pop_meta["subtitle"]
        if not sellers:
            pop_subtitle = pop_meta["subtitle"] + " (fallback: want-to-play)"
        sections_data.append(
            {
                "slug": pop_meta["slug"],
                "catalog_slug": pop_meta["catalog_slug"],
                "name": pop_meta["name"],
                "subtitle": pop_subtitle,
                "games": popular_items,
            }
        )

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections_data,
    }
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("IGDB home cache refreshed: %s sections", len(sections_data))
    return {"sections": len(sections_data), "updated_at": payload["updated_at"]}


def load_igdb_home_cache() -> dict | None:
    if not CACHE_FILE.is_file():
        return None
    try:
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cache_age_hours() -> float | None:
    if not CACHE_FILE.is_file():
        return None
    return (time.time() - CACHE_FILE.stat().st_mtime) / 3600


def igdb_cache_needs_refresh() -> bool:
    age = _cache_age_hours()
    if age is None:
        return bool(credentials_from_env())
    return age >= CACHE_MAX_AGE_HOURS


def merge_home_section_caches(steam_cache: dict | None) -> dict | None:
    """Prepend IGDB sections to Steam home sections for /api/home."""
    base = dict(steam_cache) if steam_cache else {"sections": [], "updated_at": None}
    igdb = load_igdb_home_cache()
    if not igdb or not (igdb.get("sections") or []):
        return steam_cache
    igdb_sections = igdb.get("sections") or []
    steam_sections = base.get("sections") or []
    igdb_slugs = {s.get("slug") for s in igdb_sections}
    merged_sections = igdb_sections + [s for s in steam_sections if s.get("slug") not in igdb_slugs]
    updated_at = base.get("updated_at")
    igdb_updated = igdb.get("updated_at")
    if igdb_updated and (not updated_at or str(igdb_updated) > str(updated_at)):
        updated_at = igdb_updated
    return {**base, "sections": merged_sections, "updated_at": updated_at}
