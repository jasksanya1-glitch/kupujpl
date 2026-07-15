"""Popular games for homepage — all sections from Steam Store lists (PL)."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, and_, or_
from sqlalchemy.orm import Session

from app.models.models import Game, Offer
from app.core.game_catalog_filter import (
    in_stock_offer_counts,
    is_hidden_from_steam_list,
    min_reviews_for_list_slug,
)
from app.parsers.steam_catalog import upsert_game_stub
from app.parsers.steam_lists import (
    fetch_genre_topsellers,
    fetch_global_topsellers,
    fetch_new_releases,
    get_steam_list_items,
    is_steam_list_slug,
)
from app.core.steam_media import steam_cover_url

logger = logging.getLogger("home_featured")

CACHE_FILE = Path(__file__).resolve().parents[2] / "tmp" / "home_sections_cache.json"
CACHE_MAX_AGE_HOURS = 8

HOME_SECTIONS = [
    {
        "slug": "top",
        "catalog_slug": "",
        "name": "🔥 Top teraz",
        "subtitle": "Najpopularniejsze gry w Polsce (Steam)",
        "steam_slug": "top",
    },
    {
        "slug": "nowe-gry",
        "catalog_slug": "nowe-gry",
        "name": "🆕 Nowe gry",
        "subtitle": "Premiery ze Steam",
        "steam_slug": "nowe-gry",
    },
    {
        "slug": "top-sprzedaz",
        "catalog_slug": "top-sprzedaz",
        "name": "🏆 Top sprzedaż",
        "subtitle": "Bestsellery Steam",
        "steam_slug": "top-sprzedaz",
    },
    {
        "slug": "akcja",
        "catalog_slug": "akcja",
        "name": "Akcja",
        "subtitle": "Top Akcja na Steam",
        "steam_slug": "akcja",
    },
    {
        "slug": "niezalezne",
        "catalog_slug": "niezalezne",
        "name": "Indie",
        "subtitle": "Indie na Steam",
        "steam_slug": "niezalezne",
    },
    {
        "slug": "przygodowe",
        "catalog_slug": "przygodowe",
        "name": "Przygodowe",
        "subtitle": "Top Przygodowe na Steam",
        "steam_slug": "przygodowe",
    },
    {
        "slug": "rekreacyjne",
        "catalog_slug": "casual",
        "name": "Casual",
        "subtitle": "Casual na Steam",
        "steam_slug": "rekreacyjne",
    },
    {
        "slug": "rpg",
        "catalog_slug": "rpg",
        "name": "RPG",
        "subtitle": "Top RPG na Steam",
        "steam_slug": "rpg",
    },
    {
        "slug": "strategie",
        "catalog_slug": "strategiczne",
        "name": "Strategiczne",
        "subtitle": "Top Strategie na Steam",
        "steam_slug": "strategie",
    },
    {
        "slug": "symulacje",
        "catalog_slug": "symulacje",
        "name": "Symulacje",
        "subtitle": "Symulacje na Steam",
        "steam_slug": "symulacje",
    },
    {
        "slug": "sportowe",
        "catalog_slug": "sportowe",
        "name": "Sportowe",
        "subtitle": "Sport na Steam",
        "steam_slug": "sportowe",
    },
]


def _fetch_section_items(steam_slug: str, *, limit: int) -> list[dict[str, Any]]:
    if steam_slug == "top":
        return fetch_global_topsellers(count=limit)
    if steam_slug == "nowe-gry":
        return fetch_new_releases(count=limit)
    if steam_slug == "top-sprzedaz":
        return fetch_genre_topsellers("top-sprzedaz", count=limit)
    if is_steam_list_slug(steam_slug):
        return fetch_genre_topsellers(steam_slug, count=limit)
    return []


def _upsert_section_games(db: Session, items: list[dict[str, Any]]) -> None:
    for item in items:
        appid = item.get("appid")
        if not appid:
            continue
        if db.query(Game).filter(Game.steam_appid == appid).first():
            continue
        try:
            upsert_game_stub(
                db,
                appid,
                item.get("title") or f"Gra {appid}",
                item.get("cover_image") or steam_cover_url(appid),
            )
        except Exception as exc:
            logger.debug("Stub upsert skip %s: %s", appid, exc)
            db.rollback()


def _best_offer_for_games(db: Session, game_ids: list[int]) -> dict[int, Offer]:
    if not game_ids:
        return {}
    mins = (
        db.query(Offer.game_id, func.min(Offer.price_pln).label("min_price"))
        .filter(Offer.game_id.in_(game_ids), Offer.in_stock == True)
        .group_by(Offer.game_id)
        .all()
    )
    if not mins:
        return {}
    clauses = [and_(Offer.game_id == gid, Offer.price_pln == min_p) for gid, min_p in mins]
    offers = db.query(Offer).filter(or_(*clauses)).all()
    best: dict[int, Offer] = {}
    for offer in offers:
        prev = best.get(offer.game_id)
        if prev is None or offer.price_pln < prev.price_pln:
            best[offer.game_id] = offer
    return best


def _enrich_cache_items(db: Session, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    appids = [item["appid"] for item in items if item.get("appid")]
    if not appids:
        return items
    games = {
        g.steam_appid: g
        for g in db.query(Game).filter(Game.steam_appid.in_(appids)).all()
    }
    best_map = _best_offer_for_games(db, [g.id for g in games.values()])
    enriched: list[dict[str, Any]] = []
    for item in items:
        row = dict(item)
        game = games.get(row.get("appid"))
        if game:
            row["game_id"] = game.id
            row["slug"] = game.slug
            if game.steam_enriched:
                row["title"] = game.title
            if game.cover_image:
                row["cover_image"] = game.cover_image
            row["release_date"] = game.release_date
            row["rating"] = game.rating
            best = best_map.get(game.id)
            if best:
                row["best_price_pln"] = best.price_pln
                row["best_price_is_official"] = best.is_official
                row["best_shop_name"] = best.shop_name
                if best.updated_at:
                    row["offers_updated_at"] = best.updated_at.isoformat()
        enriched.append(row)
    return enriched


def refresh_home_cache(db: Session, *, games_per_section: int = 12) -> dict:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    sections_data = []
    used_appids: set[int] = set()

    for section in HOME_SECTIONS:
        steam_slug = section.get("steam_slug") or section["slug"]
        min_reviews = min_reviews_for_list_slug(steam_slug)
        items = _fetch_section_items(steam_slug, limit=games_per_section * 2)

        deduped: list[dict[str, Any]] = []
        for item in items:
            aid = item.get("appid")
            if not aid or aid in used_appids:
                continue
            used_appids.add(aid)
            deduped.append(item)
            if len(deduped) >= games_per_section:
                break

        if not deduped:
            continue

        games_by_appid = {
            g.steam_appid: g
            for g in db.query(Game).filter(
                Game.steam_appid.in_([item["appid"] for item in deduped if item.get("appid")])
            ).all()
        }
        offer_counts = in_stock_offer_counts(db, [g.id for g in games_by_appid.values()])
        deduped = [
            item
            for item in deduped
            if not is_hidden_from_steam_list(
                games_by_appid.get(item.get("appid")),
                list_slug=steam_slug,
                item=item,
                min_reviews=min_reviews,
                in_stock_offers=(
                    offer_counts.get(games_by_appid[item["appid"]].id, 0)
                    if item.get("appid") in games_by_appid
                    and games_by_appid[item["appid"]].steam_enriched
                    and steam_slug != "nowe-gry"
                    else None
                ),
            )
        ]
        if not deduped:
            continue

        _upsert_section_games(db, deduped)
        try:
            db.commit()
        except Exception:
            db.rollback()

        deduped = _enrich_cache_items(db, deduped)

        sections_data.append(
            {
                "slug": section["slug"],
                "catalog_slug": section.get("catalog_slug") or section["slug"],
                "name": section["name"],
                "subtitle": section["subtitle"],
                "games": deduped,
            }
        )

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections_data,
    }
    CACHE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Home cache refreshed from Steam: %s sections", len(sections_data))
    return {"sections": len(sections_data), "updated_at": payload["updated_at"]}


def _load_cache() -> dict | None:
    if not CACHE_FILE.is_file():
        return None
    try:
        import time

        age_h = (time.time() - CACHE_FILE.stat().st_mtime) / 3600
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        data["_age_hours"] = age_h
        return data
    except Exception:
        return None


def cache_needs_refresh() -> bool:
    cache = _load_cache()
    if not cache:
        return True
    return cache.get("_age_hours", 999) >= CACHE_MAX_AGE_HOURS


def warm_steam_lists() -> None:
    """Pre-fetch Steam list caches used by home + catalog."""
    for slug in ("top", "nowe-gry", "top-sprzedaz", "akcja", "rpg", "niezalezne"):
        try:
            get_steam_list_items(slug)
        except Exception as exc:
            logger.warning("Steam list warm failed for %s: %s", slug, exc)
