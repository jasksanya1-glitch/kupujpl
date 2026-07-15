"""
Steam catalog: discover via GetAppList (full) or store search, enrich via appdetails.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import requests
from sqlalchemy.orm import Session

from app.core.category_visibility import is_hidden_public_category_slug
from app.core.steam_media import normalize_cover_url, steam_cover_url
from app.core.game_catalog_filter import apply_appdetails_metadata
from app.core.steam_reviews import apply_review_summary_to_game, fetch_review_summary
from app.models.models import Category, Game, Offer, game_categories

logger = logging.getLogger("steam_catalog")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}

SEARCH_URL = "https://store.steampowered.com/search/results/"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
ISTORE_APPLIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
STEAMSPY_URL = "https://steamspy.com/api.php"

STEAMSPY_GENRES = [
    "Action",
    "Indie",
    "Adventure",
    "Casual",
    "Strategy",
    "RPG",
    "Simulation",
    "Early Access",
    "Racing",
    "Sports",
    "Massively Multiplayer",
    "Design & Illustration",
    "Education",
    "Utilities",
    "Video Production",
]

ALLOWED_TYPES = frozenset(
    t.strip().lower()
    for t in os.environ.get("STEAM_ENRICH_APP_TYPES", "game,dlc").split(",")
    if t.strip()
) or {"game"}

SEARCH_SORTS = [
    "Released_DESC",
    "Price_ASC",
    "Price_DESC",
    "Metascore",
    "Name_ASC",
    "Relevance",
]

SEARCH_EXTRAS = ["", "&specials=1", "&filter=ut2"]

TMP_DIR = Path(__file__).resolve().parents[2] / "tmp"
PROGRESS_FILE = TMP_DIR / "catalog_progress.json"
APPLIST_CACHE = TMP_DIR / "steam_applist.json"

REQUEST_DELAY = 0.55
APPLIST_MAX_AGE_HOURS = 72

DiscoverSource = Literal["auto", "istore", "steamspy", "search", "both"]


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-") or "gra"


def _save_progress(data: dict) -> None:
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_catalog_progress() -> dict:
    if not PROGRESS_FILE.is_file():
        return {"phase": "idle", "discovered": 0, "stubs": 0, "enriched": 0}
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"phase": "idle", "discovered": 0, "stubs": 0, "enriched": 0}


def _search_page(start: int, sort_by: str, extra: str = "") -> list[dict[str, Any]]:
    params = {
        "json": 1,
        "cc": "pl",
        "l": "polish",
        "start": start,
        "count": 50,
        "sort_by": sort_by,
    }
    url = SEARCH_URL + "?" + "&".join(f"{k}={v}" for k, v in params.items()) + extra
    for attempt in range(1, 4):
        try:
            r = requests.get(url, timeout=25, headers=HEADERS)
            if r.status_code == 429:
                time.sleep(2.0 * attempt)
                continue
            r.raise_for_status()
            items = r.json().get("items") or []
            out = []
            for it in items:
                logo = it.get("logo") or ""
                m = re.search(r"/apps/(\d+)/", logo)
                if not m:
                    continue
                cover = normalize_cover_url(logo) or steam_cover_url(int(m.group(1)))
                out.append(
                    {
                        "appid": int(m.group(1)),
                        "title": (it.get("name") or "").strip(),
                        "cover_image": cover,
                    }
                )
            return out
        except Exception as exc:
            logger.warning("Steam search failed start=%s sort=%s: %s", start, sort_by, exc)
            if attempt < 3:
                time.sleep(1.5 * attempt)
    return []


def fetch_istore_applist(api_key: str) -> list[dict[str, Any]]:
    """Official paginated Steam store app list (games only)."""
    items: list[dict[str, Any]] = []
    last_appid = 0
    while True:
        r = requests.get(
            ISTORE_APPLIST_URL,
            params={
                "key": api_key,
                "include_games": 1,
                "include_dlc": 0,
                "include_software": 0,
                "include_videos": 0,
                "include_hardware": 0,
                "max_results": 50000,
                "last_appid": last_appid,
            },
            timeout=90,
            headers=HEADERS,
        )
        r.raise_for_status()
        apps = r.json().get("response", {}).get("apps") or []
        if not apps:
            break
        for app in apps:
            items.append(
                {
                    "appid": int(app["appid"]),
                    "title": (app.get("name") or "").strip(),
                }
            )
        last_appid = int(apps[-1]["appid"])
        if len(apps) < 50000:
            break
        time.sleep(0.5)
    logger.info("IStoreService applist: %s apps", len(items))
    return items


def discover_from_steamspy(*, max_all_pages: int = 100) -> list[dict[str, Any]]:
    """Discover games via SteamSpy (no API key; ~100k+ with genre supplement)."""
    seen: dict[int, str] = {}

    for page in range(max_all_pages):
        try:
            r = requests.get(
                STEAMSPY_URL,
                params={"request": "all", "page": page},
                timeout=45,
                headers=HEADERS,
            )
            if r.status_code != 200:
                break
            data = r.json()
            if not data:
                break
            for aid, info in data.items():
                seen[int(aid)] = (info.get("name") or "").strip()
        except Exception as exc:
            logger.warning("SteamSpy all page %s failed: %s", page, exc)
            if page > 0:
                break
        time.sleep(0.35)

    for genre in STEAMSPY_GENRES:
        try:
            r = requests.get(
                STEAMSPY_URL,
                params={"request": "genre", "genre": genre},
                timeout=90,
                headers=HEADERS,
            )
            if r.status_code != 200:
                continue
            data = r.json()
            if not isinstance(data, dict):
                continue
            for aid, info in data.items():
                seen[int(aid)] = (info.get("name") or "").strip()
        except Exception as exc:
            logger.warning("SteamSpy genre %s failed: %s", genre, exc)
        time.sleep(1.0)

    out = [{"appid": aid, "title": title} for aid, title in seen.items()]
    logger.info("SteamSpy discovered %s unique app IDs", len(out))
    return out


def fetch_steam_applist(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Full Steam catalog for stub import. Cached locally for 72h."""
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    if not force_refresh and APPLIST_CACHE.is_file():
        age_h = (time.time() - APPLIST_CACHE.stat().st_mtime) / 3600
        if age_h < APPLIST_MAX_AGE_HOURS:
            try:
                cached = json.loads(APPLIST_CACHE.read_text(encoding="utf-8"))
                if isinstance(cached, list) and cached:
                    logger.info("Using cached Steam catalog (%s apps)", len(cached))
                    return cached
            except Exception:
                pass

    api_key = (os.environ.get("STEAM_WEB_API_KEY") or "").strip()
    if api_key:
        logger.info("Downloading Steam catalog via IStoreService …")
        for attempt in range(1, 4):
            try:
                out = fetch_istore_applist(api_key)
                if out:
                    APPLIST_CACHE.write_text(
                        json.dumps(out, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    return out
            except Exception as exc:
                logger.warning("IStoreService attempt %s failed: %s", attempt, exc)
                time.sleep(3.0 * attempt)

    logger.info("Downloading Steam catalog via SteamSpy …")
    out = discover_from_steamspy()
    if not out:
        raise RuntimeError("Could not download Steam catalog (SteamSpy failed)")
    APPLIST_CACHE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


def discover_from_applist(*, force_refresh: bool = False) -> list[dict[str, Any]]:
    """All Steam app IDs (IStoreService if key set, else SteamSpy)."""
    return fetch_steam_applist(force_refresh=force_refresh)


def discover_steam_games(max_pages: int = 250) -> list[dict[str, Any]]:
    """Collect unique games from Steam store search (multiple sorts)."""
    seen: set[int] = set()
    ordered: list[dict[str, Any]] = []

    for extra in SEARCH_EXTRAS:
        for sort in SEARCH_SORTS:
            empty_streak = 0
            for page in range(max_pages):
                batch = _search_page(page * 50, sort, extra)
                if not batch:
                    empty_streak += 1
                    if empty_streak >= 2:
                        break
                    continue
                empty_streak = 0
                for item in batch:
                    aid = item["appid"]
                    if aid in seen:
                        continue
                    seen.add(aid)
                    ordered.append(item)
                time.sleep(0.4)
    logger.info("Discovered %s unique Steam app IDs", len(ordered))
    return ordered


def fetch_appdetails(appid: int) -> dict | None:
    for attempt in range(1, 4):
        try:
            r = requests.get(
                APPDETAILS_URL,
                params={"appids": appid, "cc": "pl", "l": "polish"},
                timeout=25,
                headers=HEADERS,
            )
            if r.status_code == 429:
                time.sleep(2.5 * attempt)
                continue
            if r.status_code != 200:
                return None
            block = r.json().get(str(appid))
            if block and block.get("success"):
                return block.get("data")
            return None
        except Exception as exc:
            logger.debug("appdetails %s attempt %s: %s", appid, attempt, exc)
            if attempt < 3:
                time.sleep(1.5 * attempt)
    return None


def _get_or_create_category(
    db: Session, name: str, kind: str, steam_id: str | None = None
) -> Category:
    slug = slugify(name)
    if kind == "feature":
        slug = f"feat-{slug}"
    cat = db.query(Category).filter(Category.slug == slug).first()
    if cat:
        return cat
    cat = Category(name=name, slug=slug, kind=kind, steam_id=steam_id)
    db.add(cat)
    db.flush()
    return cat


def _assign_categories(db: Session, game: Game, data: dict) -> None:
    game.categories.clear()
    for g in data.get("genres") or []:
        name = (g.get("description") or "").strip()
        if not name:
            continue
        if is_hidden_public_category_slug(slugify(name)):
            continue
        cat = _get_or_create_category(db, name, "genre", str(g.get("id") or ""))
        if cat not in game.categories:
            game.categories.append(cat)
    for c in data.get("categories") or []:
        name = (c.get("description") or "").strip()
        if not name:
            continue
        cat = _get_or_create_category(db, name, "feature", str(c.get("id") or ""))
        if cat not in game.categories:
            game.categories.append(cat)


def _upsert_steam_offer(db: Session, game: Game, appid: int, data: dict) -> None:
    price_overview = data.get("price_overview")
    if not price_overview:
        is_free = data.get("is_free")
        if not is_free:
            return
        price_pln = 0.0
        original_price_pln = 0.0
    else:
        price_pln = price_overview.get("final", 0) / 100.0
        original_price_pln = price_overview.get("initial", 0) / 100.0

    affiliate_url = f"https://store.steampowered.com/app/{appid}"
    offer = (
        db.query(Offer)
        .filter(Offer.game_id == game.id, Offer.shop_name == "Steam")
        .first()
    )
    if offer:
        prev_price = float(offer.price_pln) if offer.price_pln is not None else None
        offer.price_pln = price_pln
        offer.original_price_pln = original_price_pln
        offer.affiliate_url = affiliate_url
        offer.in_stock = True
        from app.core.price_history import record_offer_price_change

        record_offer_price_change(
            db,
            game_id=game.id,
            shop_name="Steam",
            price_pln=price_pln,
            previous_price=prev_price,
        )
    else:
        db.add(
            Offer(
                game_id=game.id,
                shop_name="Steam",
                price_pln=price_pln,
                original_price_pln=original_price_pln,
                affiliate_url=affiliate_url,
                is_official=True,
                in_stock=True,
            )
        )
        from app.core.price_history import record_offer_price_change

        record_offer_price_change(
            db,
            game_id=game.id,
            shop_name="Steam",
            price_pln=price_pln,
            previous_price=None,
        )


def refresh_steam_offer_for_game(db: Session, game: Game) -> bool:
    """Update Steam store price from appdetails (PL region)."""
    if not game.steam_appid:
        return False
    data = fetch_appdetails(game.steam_appid)
    if not data:
        return False
    _upsert_steam_offer(db, game, game.steam_appid, data)
    return True


def upsert_game_stub(db: Session, appid: int, title: str, cover_image: str | None) -> Game:
    cover = cover_image or steam_cover_url(appid)
    existing = db.query(Game).filter(Game.steam_appid == appid).first()
    slug = f"{slugify(title)}-{appid}"
    if existing:
        existing.title = title or existing.title
        if cover:
            existing.cover_image = cover
        return existing
    game = Game(
        title=title or f"Steam {appid}",
        slug=slug,
        cover_image=cover,
        steam_appid=appid,
        steam_enriched=False,
    )
    db.add(game)
    db.flush()
    return game


def enrich_game(db: Session, game: Game) -> bool:
    if not game.steam_appid:
        return False
    data = fetch_appdetails(game.steam_appid)
    time.sleep(REQUEST_DELAY)
    if not data:
        return False

    app_type = (data.get("type") or "").lower()
    apply_appdetails_metadata(game, data)

    if app_type and app_type not in ALLOWED_TYPES:
        summary = fetch_review_summary(game.steam_appid)
        apply_review_summary_to_game(game, summary)
        game.steam_enriched = True
        return True

    title = data.get("name") or game.title
    game.title = title
    game.slug = f"{slugify(title)}-{game.steam_appid}"
    game.cover_image = data.get("header_image") or game.cover_image or steam_cover_url(game.steam_appid)
    desc = (data.get("short_description") or "")[:2000]
    game.description = desc
    summary = fetch_review_summary(game.steam_appid)
    apply_review_summary_to_game(game, summary)
    game.steam_enriched = True

    _assign_categories(db, game, data)
    _upsert_steam_offer(db, game, game.steam_appid, data)
    return True


def refresh_category_counts(db: Session) -> None:
    cats = db.query(Category).all()
    for cat in cats:
        cat.game_count = (
            db.query(game_categories.c.game_id)
            .filter(game_categories.c.category_id == cat.id)
            .count()
        )


def _discover_all(
    *,
    source: DiscoverSource = "auto",
    max_pages: int = 250,
    force_applist_refresh: bool = False,
) -> list[dict[str, Any]]:
    seen: set[int] = set()
    ordered: list[dict[str, Any]] = []

    def _add(items: list[dict[str, Any]]) -> None:
        for item in items:
            aid = item["appid"]
            if aid in seen:
                continue
            seen.add(aid)
            ordered.append(item)

    use_catalog = source in ("auto", "istore", "steamspy", "both")
    use_search = source in ("search", "both")

    if use_catalog:
        if source == "steamspy":
            _add(discover_from_steamspy())
        elif source == "istore":
            api_key = (os.environ.get("STEAM_WEB_API_KEY") or "").strip()
            if not api_key:
                raise RuntimeError("STEAM_WEB_API_KEY is required for source=istore")
            _add(fetch_istore_applist(api_key))
        else:
            _add(discover_from_applist(force_refresh=force_applist_refresh))
    if use_search:
        _add(discover_steam_games(max_pages=max_pages))
    return ordered


def import_stubs_batch(
    db: Session,
    items: list[dict[str, Any]],
    *,
    start: int = 0,
    batch_size: int = 2000,
    existing_ids: set[int] | None = None,
) -> dict:
    """Insert game stubs from applist slice (for resumable bulk import)."""
    progress = get_catalog_progress()
    progress.setdefault("phase", "stubs")
    end = min(start + batch_size, len(items))
    if existing_ids is None:
        existing_ids = {
            row[0]
            for row in db.query(Game.steam_appid).filter(Game.steam_appid.isnot(None)).all()
        }
    created = 0
    for item in items[start:end]:
        aid = item["appid"]
        if aid in existing_ids:
            continue
        upsert_game_stub(db, aid, item["title"], item.get("cover_image"))
        existing_ids.add(aid)
        created += 1
    db.commit()
    progress["discovered"] = len(items)
    progress["stubs"] = len(existing_ids)
    progress["stub_cursor"] = end
    progress["phase"] = "stubs" if end < len(items) else "enrich"
    progress["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_progress(progress)
    return {
        "processed": end - start,
        "created": created,
        "cursor": end,
        "total": len(items),
        "done": end >= len(items),
        "stubs": len(existing_ids),
    }


def run_steam_catalog_import(
    db: Session,
    *,
    source: DiscoverSource = "auto",
    max_pages: int = 250,
    enrich_limit: int = 5000,
    force_applist_refresh: bool = False,
    stub_batch_size: int = 2000,
) -> dict:
    progress = {
        "phase": "discover",
        "source": source,
        "discovered": 0,
        "stubs": 0,
        "enriched": 0,
        "skipped": 0,
        "errors": 0,
        "stub_cursor": 0,
    }
    _save_progress(progress)

    discovered = _discover_all(
        source=source,
        max_pages=max_pages,
        force_applist_refresh=force_applist_refresh,
    )
    progress["discovered"] = len(discovered)
    progress["phase"] = "stubs"
    _save_progress(progress)

    cursor = 0
    existing_ids = {
        row[0]
        for row in db.query(Game.steam_appid).filter(Game.steam_appid.isnot(None)).all()
    }
    while cursor < len(discovered):
        batch = import_stubs_batch(
            db,
            discovered,
            start=cursor,
            batch_size=stub_batch_size,
            existing_ids=existing_ids,
        )
        cursor = batch["cursor"]
        progress["stubs"] = batch["stubs"]
        progress["stub_cursor"] = cursor
        _save_progress(get_catalog_progress())
    progress = get_catalog_progress()

    progress["phase"] = "enrich"
    _save_progress(progress)

    pending = (
        db.query(Game)
        .filter(Game.steam_appid.isnot(None), Game.steam_enriched == False)
        .limit(enrich_limit)
        .all()
    )

    for game in pending:
        try:
            ok = enrich_game(db, game)
            if ok:
                progress["enriched"] += 1
            else:
                progress["skipped"] += 1
            if (progress["enriched"] + progress["skipped"]) % 50 == 0:
                db.commit()
                refresh_category_counts(db)
                db.commit()
                _save_progress(progress)
        except Exception:
            progress["errors"] += 1
            db.rollback()

    db.commit()
    refresh_category_counts(db)
    db.commit()

    progress["phase"] = "done"
    _save_progress(progress)
    logger.info("Catalog import done: %s", progress)
    return progress


def enrich_pending_batch(db: Session, limit: int = 200) -> dict:
    """Continue enriching games not yet fully loaded from Steam."""
    progress = get_catalog_progress()
    progress["phase"] = "enrich"
    pending = (
        db.query(Game)
        .filter(Game.steam_appid.isnot(None), Game.steam_enriched == False)
        .limit(limit)
        .all()
    )
    enriched = skipped = 0
    for game in pending:
        try:
            if enrich_game(db, game):
                enriched += 1
            else:
                skipped += 1
        except Exception:
            db.rollback()
            skipped += 1
    db.commit()
    refresh_category_counts(db)
    db.commit()
    progress["enriched"] = progress.get("enriched", 0) + enriched
    progress["skipped"] = progress.get("skipped", 0) + skipped
    remaining = (
        db.query(Game)
        .filter(Game.steam_appid.isnot(None), Game.steam_enriched == False)
        .count()
    )
    progress["remaining"] = remaining
    progress["phase"] = "done" if remaining == 0 else "enrich"
    _save_progress(progress)
    return {"enriched": enriched, "skipped": skipped, "remaining": remaining}


def backfill_cover_images(db: Session, *, batch_size: int = 2000, commit_every: int = 500) -> dict:
    """Set Steam CDN header URL for games missing cover_image."""
    from sqlalchemy import or_
    import time

    updated = 0
    while True:
        games = (
            db.query(Game)
            .filter(
                Game.steam_appid.isnot(None),
                or_(Game.cover_image.is_(None), Game.cover_image == ""),
            )
            .limit(batch_size)
            .all()
        )
        if not games:
            break
        batch_count = 0
        for game in games:
            game.cover_image = steam_cover_url(game.steam_appid)
            updated += 1
            batch_count += 1
            if batch_count % commit_every == 0:
                for attempt in range(5):
                    try:
                        db.commit()
                        break
                    except Exception:
                        db.rollback()
                        time.sleep(1.0 * (attempt + 1))
                else:
                    logger.warning("Backfill commit failed after retries")
        for attempt in range(5):
            try:
                db.commit()
                break
            except Exception:
                db.rollback()
                time.sleep(1.0 * (attempt + 1))
    logger.info("Backfilled %s cover images", updated)
    return {"updated": updated}
