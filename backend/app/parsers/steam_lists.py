"""Steam Store search lists (topsellers, new releases, genres) for PL region."""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests
from sqlalchemy.orm import Session

from app.core.steam_media import normalize_cover_url, steam_cover_url
from app.core.game_catalog_filter import (
    fetch_steam_list_page_items,
    min_reviews_for_list_slug,
)
from app.models.models import Category, Game, Offer
from app.parsers.steam_catalog import upsert_game_stub

logger = logging.getLogger("steam_lists")

SEARCH_URL = "https://store.steampowered.com/search/results/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

CACHE_DIR = Path(__file__).resolve().parents[2] / "tmp" / "steam_lists"
CACHE_TTL_SECONDS = 3600
CACHE_VERSION = 4
MAX_CACHED_ITEMS = 400
PAGE_SIZE = 50

GENRE_SLUG_TO_TAG: dict[str, str] = {
    "akcja": "19",
    "przygodowe": "21",
    "rpg": "122",
    "strategiczne": "9",
    "strategie": "9",
    "niezalezne": "492",
    "indie": "492",
    "symulacje": "599",
    "sportowe": "701",
    "casual": "597",
    "rekreacyjne": "597",
    "wyscigowe": "699",
    "horror": "1667",
    "mmo": "128",
    "wczesny-dostep": "493",
}

CURATED_LISTS: dict[str, dict[str, str | None]] = {
    # Match Steam store: New releases → sort by release date, games only (category1=998).
    "nowe-gry": {
        "filter": "newreleases",
        "tags": None,
        "sort_by": "Released_DESC",
        "category1": "998",
        "hidef2p": "1",
    },
    "top-sprzedaz": {
        "filter": "topsellers",
        "tags": None,
        "sort_by": None,
        "category1": "998",
        "hidef2p": "1",
    },
    "top": {"filter": "topsellers", "tags": None, "sort_by": None, "category1": "998", "hidef2p": None},
}


def is_steam_list_slug(slug: str | None) -> bool:
    if not slug:
        return False
    return slug.strip().lower() in {**CURATED_LISTS, **GENRE_SLUG_TO_TAG}


def _cover_from_search_logo(logo: str, appid: int) -> str:
    """Steam search returns working capsule_sm_120 URLs — do not rewrite to header."""
    cover = normalize_cover_url(logo)
    if cover:
        return cover
    return steam_cover_url(appid) or ""


def parse_search_items(items: list[dict]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for it in items:
        logo = it.get("logo") or ""
        match = re.search(r"/apps/(\d+)/", logo)
        if not match:
            continue
        appid = int(match.group(1))
        if appid in seen:
            continue
        seen.add(appid)
        out.append(
            {
                "appid": appid,
                "title": (it.get("name") or "").strip(),
                "cover_image": _cover_from_search_logo(logo, appid),
            }
        )
    return out


def _list_spec(slug: str, db: Session | None = None) -> dict[str, str | None] | None:
    key = slug.strip().lower()
    if key in CURATED_LISTS:
        return CURATED_LISTS[key]
    tag = GENRE_SLUG_TO_TAG.get(key)
    if tag:
        return {"filter": "topsellers", "tags": tag, "sort_by": None, "category1": None, "hidef2p": None}
    if db is not None:
        cat = db.query(Category).filter(Category.slug == key).first()
        if cat and cat.slug in GENRE_SLUG_TO_TAG:
            return {
                "filter": "topsellers",
                "tags": GENRE_SLUG_TO_TAG[cat.slug],
                "sort_by": None,
                "category1": None,
                "hidef2p": None,
            }
    return None


def _cache_path(slug: str) -> Path:
    return CACHE_DIR / f"{slug.strip().lower()}.json"


def _load_cached_list(slug: str) -> dict[str, Any] | None:
    path = _cache_path(slug)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["_age_seconds"] = time.time() - path.stat().st_mtime
        return data
    except Exception:
        return None


def _save_cached_list(slug: str, items: list[dict[str, Any]], total_count: int | None) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "slug": slug,
        "cache_version": CACHE_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_count": total_count or len(items),
        "items": items,
    }
    _cache_path(slug).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def fetch_steam_search_page(
    *,
    start: int = 0,
    count: int = PAGE_SIZE,
    filter_name: str | None = "topsellers",
    tags: str | None = None,
    sort_by: str | None = None,
    category1: str | None = None,
    hidef2p: int | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    params: dict[str, Any] = {
        "json": 1,
        "cc": "pl",
        "l": "polish",
        "start": start,
        "count": count,
    }
    if filter_name:
        params["filter"] = filter_name
    if tags:
        params["tags"] = tags
    if sort_by:
        params["sort_by"] = sort_by
    if category1:
        params["category1"] = category1
    if hidef2p is not None:
        params["hidef2p"] = hidef2p

    url = f"{SEARCH_URL}?{urlencode(params)}"
    for attempt in range(1, 4):
        try:
            response = requests.get(url, timeout=25, headers=HEADERS)
            if response.status_code == 429:
                time.sleep(2.0 * attempt)
                continue
            response.raise_for_status()
            payload = response.json() or {}
            items = parse_search_items(payload.get("items") or [])
            total = payload.get("total_count")
            if isinstance(total, str) and total.isdigit():
                total = int(total)
            elif not isinstance(total, int):
                total = None
            return items, total
        except Exception as exc:
            logger.warning("Steam list fetch failed (start=%s): %s", start, exc)
            if attempt < 3:
                time.sleep(1.5 * attempt)
    return [], None


def refresh_steam_list(slug: str, db: Session | None = None) -> list[dict[str, Any]]:
    spec = _list_spec(slug, db)
    if not spec:
        return []

    items: list[dict[str, Any]] = []
    seen: set[int] = set()
    total_count: int | None = None
    start = 0

    while start < MAX_CACHED_ITEMS:
        batch, total = fetch_steam_search_page(
            start=start,
            count=PAGE_SIZE,
            filter_name=spec.get("filter"),
            tags=spec.get("tags"),
            sort_by=spec.get("sort_by"),
            category1=spec.get("category1"),
            hidef2p=int(spec["hidef2p"]) if spec.get("hidef2p") else None,
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
        if len(batch) < PAGE_SIZE:
            break
        start += PAGE_SIZE
        time.sleep(0.35)

    _save_cached_list(slug, items, total_count or len(items))
    logger.info("Steam list %s refreshed: %s items", slug, len(items))
    return items


def get_steam_list_items(
    slug: str,
    db: Session | None = None,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    key = slug.strip().lower()
    if not force_refresh:
        cached = _load_cached_list(key)
        if cached and cached.get("_age_seconds", 999999) < CACHE_TTL_SECONDS:
            if cached.get("cache_version") == CACHE_VERSION:
                items = cached.get("items") or []
                total = int(cached.get("total_count") or len(items))
                return items, total

    items = refresh_steam_list(key, db)
    return items, len(items)


def fetch_steam_list_slice(
    slug: str,
    db: Session,
    *,
    page: int = 1,
    limit: int = 48,
) -> tuple[list[dict[str, Any]], int]:
    if not _list_spec(slug, db):
        return [], 0
    items, _total = get_steam_list_items(slug, db)
    return fetch_steam_list_page_items(
        db,
        items,
        page=page,
        limit=limit,
        min_reviews=min_reviews_for_list_slug(slug),
        list_slug=slug,
    )


def sync_steam_list_games(db: Session, items: list[dict[str, Any]]) -> list[int]:
    """Upsert Steam list rows and refresh title/cover; return appids touched."""
    appids: list[int] = []
    for item in items:
        appid = item.get("appid")
        if not appid:
            continue
        title = item.get("title") or f"Gra {appid}"
        cover = item.get("cover_image") or steam_cover_url(appid)
        try:
            game = upsert_game_stub(db, appid, title, cover)
            if cover and game.cover_image != cover:
                game.cover_image = cover
            if title and (not game.steam_enriched or game.title.startswith("Gra ")):
                game.title = title
            appids.append(appid)
        except Exception as exc:
            logger.debug("Steam sync skip %s: %s", appid, exc)
            db.rollback()
    return appids


def ensure_steam_stubs(db: Session, items: list[dict[str, Any]]) -> None:
    sync_steam_list_games(db, items)


def sync_hydrate_steam_list_games(db: Session, appids: list[int], *, limit: int = 8) -> int:
    """Enrich a few visible games synchronously so cards have cover/price/desc."""
    from app.parsers.steam_catalog import enrich_game, refresh_steam_offer_for_game

    done = 0
    for appid in appids:
        if done >= limit:
            break
        game = (
            db.query(Game)
            .filter(Game.steam_appid == appid, Game.steam_enriched == False)
            .first()
        )
        if not game:
            continue
        try:
            if enrich_game(db, game):
                db.commit()
                done += 1
            else:
                db.rollback()
        except Exception as exc:
            logger.debug("Sync enrich failed for %s: %s", appid, exc)
            db.rollback()

    for appid in appids[:limit]:
        game = db.query(Game).filter(Game.steam_appid == appid).first()
        if not game or not game.steam_enriched:
            continue
        has_steam = (
            db.query(Offer.id)
            .filter(
                Offer.game_id == game.id,
                Offer.shop_name == "Steam",
                Offer.in_stock == True,
            )
            .first()
        )
        if has_steam:
            continue
        try:
            if refresh_steam_offer_for_game(db, game):
                db.commit()
        except Exception:
            db.rollback()
    return done


def hydrate_steam_list_games(appids: list[int], *, limit: int = 18) -> dict[str, int]:
    """Background: enrich metadata + Steam price + missing shop offers."""
    from app.core.database import SessionLocal
    from app.parsers.steam_catalog import enrich_game, refresh_steam_offer_for_game
    from app.parsers.game_offers import refresh_offers_for_game

    enriched = offers = 0
    db = SessionLocal()
    try:
        for appid in appids[:limit]:
            game = db.query(Game).filter(Game.steam_appid == appid).first()
            if not game:
                continue
            try:
                if not game.steam_enriched:
                    if enrich_game(db, game):
                        db.commit()
                        enriched += 1
                    else:
                        db.rollback()
                        continue
                elif not db.query(Offer).filter(
                    Offer.game_id == game.id,
                    Offer.shop_name == "Steam",
                    Offer.in_stock == True,
                ).first():
                    if refresh_steam_offer_for_game(db, game):
                        db.commit()
                        offers += 1
                    else:
                        db.rollback()
                refresh_offers_for_game(game.id, fill_missing=True, fast=False)
            except Exception as exc:
                logger.debug("Hydrate failed for %s: %s", appid, exc)
                db.rollback()
    finally:
        db.close()
    return {"enriched": enriched, "steam_offers": offers}


def fetch_global_topsellers(*, count: int = 12) -> list[dict[str, Any]]:
    items, _ = get_steam_list_items("top")
    return items[:count]


def fetch_new_releases(*, count: int = 12) -> list[dict[str, Any]]:
    items, _ = get_steam_list_items("nowe-gry")
    return items[:count]


def fetch_genre_topsellers(slug: str, *, count: int = 12) -> list[dict[str, Any]]:
    items, _ = get_steam_list_items(slug)
    return items[:count]
