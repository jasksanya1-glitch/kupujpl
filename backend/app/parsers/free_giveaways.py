"""Monitor limited-time free game giveaways (Epic Free Games + Steam 100% off)."""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.core.database import BASE_DIR
from app.core.affiliate import make_affiliate_link
from app.models.models import Game, Offer

logger = logging.getLogger("free_giveaways")

CACHE_PATH = BASE_DIR / "tmp" / "free_giveaways.json"
CACHE_TTL_SEC = 30 * 60
EPIC_FREE_URL = (
    "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    "?locale=pl&country=PL&allowCountries=PL"
)
STEAM_SEARCH_FREE_SPECIALS = (
    "https://store.steampowered.com/search/results/"
    "?query=&start=0&count=50&dynamic_data=&sort_by=_ASC"
    "&maxprice=free&specials=1&infinite=1&cc=pl&l=polish"
)
STEAM_STORE = "https://store.steampowered.com/app"

_LOCK = threading.Lock()
_STARTED = False

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return value


def _epic_page_slug(element: dict) -> str | None:
    for mapping in (element.get("offerMappings") or []) + (
        (element.get("catalogNs") or {}).get("mappings") or []
    ):
        slug = (mapping or {}).get("pageSlug")
        if slug:
            return str(slug).split("/")[0]
    product = element.get("productSlug") or ""
    if product:
        return str(product).split("/")[0]
    url_slug = element.get("urlSlug")
    if url_slug and not re.fullmatch(r"[0-9a-f]{32}", str(url_slug)):
        return str(url_slug)
    return None


def _epic_cover(element: dict) -> str | None:
    images = element.get("keyImages") or []
    preferred = ("OfferImageWide", "Thumbnail", "DieselStoreFrontWide", "OfferImageTall")
    by_type = {img.get("type"): img.get("url") for img in images if img.get("url")}
    for key in preferred:
        if by_type.get(key):
            return by_type[key]
    return next(iter(by_type.values()), None)


def _epic_promo_window(element: dict, *, upcoming: bool) -> tuple[str | None, str | None]:
    promotions = element.get("promotions") or {}
    bucket = promotions.get("upcomingPromotionalOffers" if upcoming else "promotionalOffers") or []
    if not bucket:
        return None, None
    offers = (bucket[0] or {}).get("promotionalOffers") or []
    if not offers:
        return None, None
    first = offers[0] or {}
    return _parse_iso(first.get("startDate")), _parse_iso(first.get("endDate"))


def fetch_epic_giveaways() -> list[dict[str, Any]]:
    try:
        res = requests.get(EPIC_FREE_URL, headers=HEADERS, timeout=20)
        res.raise_for_status()
        payload = res.json()
    except Exception as exc:
        logger.warning("Epic free promotions fetch failed: %s", exc)
        return []

    elements = (
        ((payload.get("data") or {}).get("Catalog") or {}).get("searchStore") or {}
    ).get("elements") or []
    out: list[dict[str, Any]] = []
    for el in elements:
        title = (el.get("title") or "").strip()
        if not title:
            continue
        price = ((el.get("price") or {}).get("totalPrice") or {})
        disc = price.get("discountPrice")
        orig = price.get("originalPrice")
        promotions = el.get("promotions") or {}
        has_current = bool(promotions.get("promotionalOffers"))
        has_upcoming = bool(promotions.get("upcomingPromotionalOffers"))
        if not has_current and not has_upcoming:
            continue

        is_free_now = has_current and disc == 0
        status = "current" if is_free_now else ("upcoming" if has_upcoming else "other")
        if status == "other":
            continue

        starts, ends = _epic_promo_window(el, upcoming=(status == "upcoming"))
        page_slug = _epic_page_slug(el)
        store_url = (
            f"https://store.epicgames.com/pl/p/{page_slug}" if page_slug else
            "https://store.epicgames.com/pl/free-games"
        )
        out.append(
            {
                "title": title,
                "shop": "Epic Games",
                "status": status,
                "store_url": store_url,
                "affiliate_url": make_affiliate_link(store_url, "Epic Games"),
                "cover_image": _epic_cover(el),
                "original_price_pln": round(int(orig) / 100.0, 2) if isinstance(orig, int) and orig > 0 else None,
                "starts_at": starts,
                "ends_at": ends,
                "source_id": page_slug or el.get("id") or el.get("urlSlug"),
                "is_permanent_free": False,
            }
        )
    return out


def fetch_steam_search_giveaways() -> list[dict[str, Any]]:
    """Steam 100% off / free specials (often empty; best-effort)."""
    try:
        res = requests.get(STEAM_SEARCH_FREE_SPECIALS, headers=HEADERS, timeout=20)
        res.raise_for_status()
        payload = res.json()
    except Exception as exc:
        logger.debug("Steam free specials search failed: %s", exc)
        return []

    html = payload.get("results_html") or ""
    if not html:
        return []
    out: list[dict[str, Any]] = []
    for m in re.finditer(
        r'data-ds-appid="(\d+)"[\s\S]*?class="title">\s*([^<]+)',
        html,
        flags=re.I,
    ):
        appid, title = m.group(1), m.group(2).strip()
        if not title:
            continue
        store_url = f"{STEAM_STORE}/{appid}/"
        out.append(
            {
                "title": title,
                "shop": "Steam",
                "status": "current",
                "store_url": store_url,
                "affiliate_url": make_affiliate_link(store_url, "Steam"),
                "cover_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/header.jpg",
                "original_price_pln": None,
                "starts_at": None,
                "ends_at": None,
                "source_id": appid,
                "steam_appid": int(appid),
                "is_permanent_free": False,
            }
        )
    return out


def fetch_steam_db_giveaways(db: Session) -> list[dict[str, Any]]:
    """Temporary Steam free: price ~0 with meaningful original price."""
    rows = (
        db.query(Offer, Game)
        .join(Game, Game.id == Offer.game_id)
        .filter(
            Offer.shop_name == "Steam",
            Offer.in_stock.is_(True),
            Offer.price_pln <= 0.01,
            Offer.original_price_pln.isnot(None),
            Offer.original_price_pln > 1.0,
            Game.is_free.isnot(True),
        )
        .order_by(Offer.original_price_pln.desc())
        .limit(40)
        .all()
    )
    out: list[dict[str, Any]] = []
    for offer, game in rows:
        appid = game.steam_appid
        store_url = f"{STEAM_STORE}/{appid}/" if appid else offer.affiliate_url
        out.append(
            {
                "title": game.title,
                "shop": "Steam",
                "status": "current",
                "store_url": store_url,
                "affiliate_url": offer.affiliate_url or make_affiliate_link(store_url, "Steam"),
                "cover_image": game.cover_image,
                "original_price_pln": float(offer.original_price_pln),
                "starts_at": None,
                "ends_at": None,
                "source_id": str(appid or game.slug),
                "steam_appid": appid,
                "slug": game.slug,
                "is_permanent_free": False,
            }
        )
    return out


def _match_catalog(db: Session, item: dict[str, Any]) -> dict[str, Any]:
    if item.get("slug"):
        return item
    appid = item.get("steam_appid")
    game = None
    if appid:
        game = db.query(Game).filter(Game.steam_appid == int(appid)).first()
    if not game:
        title = (item.get("title") or "").strip()
        if title:
            game = db.query(Game).filter(Game.title.ilike(title)).first()
            if not game and len(title) > 4:
                game = (
                    db.query(Game)
                    .filter(Game.title.ilike(f"{title[:40]}%"))
                    .order_by(Game.steam_review_count.desc())
                    .first()
                )
    if game:
        item = dict(item)
        item["slug"] = game.slug
        if not item.get("cover_image"):
            item["cover_image"] = game.cover_image
        if game.steam_appid and not item.get("steam_appid"):
            item["steam_appid"] = game.steam_appid
    return item


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = f"{item.get('shop')}|{(item.get('title') or '').lower()}|{item.get('source_id')}"
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def refresh_free_giveaways(db: Session | None = None) -> dict[str, Any]:
    own_session = False
    if db is None:
        from app.core.database import SessionLocal

        db = SessionLocal()
        own_session = True
    try:
        epic = fetch_epic_giveaways()
        steam_search = fetch_steam_search_giveaways()
        steam_db = fetch_steam_db_giveaways(db)
        items = _dedupe(epic + steam_search + steam_db)
        items = [_match_catalog(db, it) for it in items]
        current = [i for i in items if i.get("status") == "current"]
        upcoming = [i for i in items if i.get("status") == "upcoming"]
        payload = {
            "updated_at": _utcnow().isoformat(),
            "current": current,
            "upcoming": upcoming,
            "items": current + upcoming,
        }
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(
            "Free giveaways refreshed: current=%s upcoming=%s",
            len(current),
            len(upcoming),
        )
        return payload
    finally:
        if own_session:
            db.close()


def load_free_giveaways(*, max_age_sec: int = CACHE_TTL_SEC) -> dict[str, Any]:
    if not CACHE_PATH.is_file():
        return {"updated_at": None, "current": [], "upcoming": [], "items": []}
    try:
        payload = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"updated_at": None, "current": [], "upcoming": [], "items": []}
    updated = payload.get("updated_at")
    if updated and max_age_sec > 0:
        try:
            ts = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age = (_utcnow() - ts.astimezone(timezone.utc)).total_seconds()
            payload["stale"] = age > max_age_sec
        except Exception:
            payload["stale"] = True
    else:
        payload["stale"] = True
    payload.setdefault("current", [])
    payload.setdefault("upcoming", [])
    payload.setdefault("items", payload.get("current", []) + payload.get("upcoming", []))
    return payload


def get_free_giveaways(db: Session, *, force: bool = False) -> dict[str, Any]:
    cached = load_free_giveaways()
    if force or cached.get("stale") or not cached.get("items"):
        try:
            return refresh_free_giveaways(db)
        except Exception as exc:
            logger.warning("Giveaway refresh failed, using cache: %s", exc)
            return cached
    return cached


def start_free_giveaways_scheduler() -> None:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True

    def _loop() -> None:
        time.sleep(8)
        while True:
            try:
                refresh_free_giveaways()
            except Exception as exc:
                logger.warning("Giveaways scheduler cycle failed: %s", exc)
            time.sleep(CACHE_TTL_SEC)

    threading.Thread(target=_loop, name="free-giveaways", daemon=True).start()
    logger.info("Free giveaways scheduler started (ttl=%ss)", CACHE_TTL_SEC)
