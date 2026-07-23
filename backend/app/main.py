from pathlib import Path
from urllib.parse import parse_qs

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI, Depends, HTTPException, Query, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, and_, or_
from typing import List, Optional, Any
import logging
import math
import os
import json
import time
import hashlib
import threading
import jwt
import html as html_lib
from datetime import datetime

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, HTMLResponse, Response

from app.core.database import get_db, init_db, SessionLocal
from app.core.steam_media import effective_cover, list_cover_image
from app.core.category_lookup import resolve_category_slug
from app.core.category_visibility import is_hidden_public_category_slug
from app.core.curated_categories import (
    is_curated_slug,
    uses_steam_list,
)
from app.core.text_search import apply_game_search, apply_search_quality_filter, search_order
from app.core.game_catalog_filter import (
    apply_appdetails_metadata,
    exclude_hidden_games_query,
    get_visible_games_count,
    in_stock_offer_counts,
    is_hidden_from_catalog,
    min_reviews_for_list_slug,
    refresh_visible_games_count_cache,
)
from app.core.steam_reviews import (
    apply_review_summary_to_game,
    fetch_review_summary,
)
from app.core.slug_lookup import resolve_game_slug, _steam_appid_from_slug_suffix
from app.core.slug_cleanup import cleanup_mistaken_stub_games
from app.core.game_audit import audit_game_catalog
from app.core.panel3_auth import (
    PANEL3_COOKIE_NAME,
    panel3_cookie_kwargs,
    panel3_cookie_value,
    panel3_gate_ok,
    require_panel3_gate,
    require_panel3_admin,
)
from app.core.admin_stats import collect_admin_stats
from app.core.admin_events import collect_admin_events
from app.core.live_dashboard import collect_live_dashboard
from app.core.local_offer_worker import apply_bulk_offers, build_offer_queue
from app.core.affiliate import make_affiliate_link, resolve_outbound_url
from app.core.affiliate_config import affiliate_env_status
from app.core.click_tracking import collect_click_stats, log_affiliate_click, prune_old_clicks
from app.core.og_image import render_og_png, render_logo_png
from app.core.offer_quality import offer_eligible_for_best_price
from app.core.site_tracking import (
    record_session_heartbeat,
    record_site_visit,
    should_block_crawler_request,
    touch_user_last_seen,
)
from app.core.site_config import public_site_info, SITE_ORIGIN
from app.core.seo_pages import (
    robots_txt,
    sitemap_index_xml,
    sitemap_games_xml,
    sitemap_categories_xml,
    sitemap_deals_xml,
    sitemap_blog_xml,
    game_landing_html,  # kept for legacy SEO helpers
    category_landing_html,
    deals_landing_html,
    blog_landing_html,
    blog_index_html,
    not_found_html,
    home_website_schema_json,
    price_history_landing_html,
)
from app.core.price_history import get_price_history, lowest_ever_label_pl
from app.core.price_alerts import ensure_telegram_link_token, set_favorite_alert, process_price_alerts
from app.core.game_page_html import game_interactive_html
from app.core.home_feeds import (
    deal_age_label,
    games_at_historical_low,
    games_freebies,
    games_new_deals,
    parent_game_for_dlc,
    related_dlc_games,
)
from app.core.shops_trust import shop_trust_badge
from app.core.telegram_bot import handle_telegram_update, bot_configured
from app.core.wykop_callback import callback_html, save_refresh_token
from app.core.deps import get_current_user
from app.core.password_reset import request_password_reset, reset_password_with_code
from app.core.user_account import change_user_password, get_account_summary
from app.core.google_auth import (
    authenticate_google_user,
    google_auth_enabled,
    google_client_id,
    issue_token_for_user,
    verify_google_credential,
)
from app.core.web_push import (
    get_vapid_public_key,
    remove_push_subscription,
    upsert_push_subscription,
    user_push_status,
    vapid_configured,
)
from app.core.security import create_access_token, get_password_hash, verify_password, SECRET_KEY, ALGORITHM
from app.models.models import Game, Offer, User, Favorite, Category, game_categories
from app.schemas.schemas import (
    GameResponse,
    GameListResponse,
    GamesPageResponse,
    HomePageResponse,
    HomeSectionResponse,
    HomeCurationResponse,
    HomeCurationUpdateRequest,
    HomeCurationImportRequest,
    HomeCurationGameResponse,
    CategoryResponse,
    UserRegister,
    UserLogin,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ChangePasswordRequest,
    AccountSummaryResponse,
    MessageResponse,
    UserResponse,
    TokenResponse,
    FavoriteGameResponse,
    FavoriteAlertUpdate,
    PriceHistoryResponse,
    PriceHistoryPoint,
    TelegramLinkResponse,
    AccountAlertsUpdate,
    PushSubscriptionIn,
    PushUnsubscribeIn,
    PushStatusResponse,
    VapidPublicKeyResponse,
    GoogleAuthRequest,
    GoogleAuthConfigResponse,
    SteamWishlistImportRequest,
    SteamWishlistImportResponse,
    OfferResponse,
    TrackVisitRequest,
    RemoteOfferBulkRequest,
    RefreshOffersResponse,
)
from app.parsers.steam_parser import import_steam_games
from app.parsers.steam_catalog import (
    run_steam_catalog_import,
    enrich_pending_batch,
    get_catalog_progress,
    backfill_cover_images,
)
from app.parsers.gog_parser import import_gog_offers
from app.parsers.epic_parser import import_epic_offers
from app.parsers.eneba_parser import import_eneba_offers
from app.parsers.kinguin_parser import import_kinguin_offers
from app.parsers.cdkeys_parser import import_cdkeys_offers
from app.parsers.gamivo_parser import import_gamivo_offers
from app.parsers.instant_gaming_parser import import_instant_gaming_offers
from app.parsers.g2a_parser import import_g2a_offers
from app.parsers.game_offers import (
    refresh_offers_for_game,
    game_needs_offer_refresh,
    MIN_SHOPS_TARGET,
)
from app.parsers.shop_scan_config import (
    EXPECTED_SHOPS,
    get_disabled_scan_shops,
    get_display_shops,
    get_scan_routing_config,
    get_scan_shops_config,
    save_disabled_scan_shops,
    save_scan_routing,
    set_shop_worker,
    toggle_scan_shop,
)
from app.parsers.tier_a_top5000 import (
    build_tier_a_queue,
    is_in_tier_a_daily_scan,
    next_tier_a_scan_at,
)
from app.parsers.tier_a_scan_state import get_tier_a_status
from app.parsers.offer_scheduler import (
    get_scheduler_status,
    run_offer_refresh_cycle,
    start_offer_scheduler,
)
from app.parsers.featured_offer_prefetch import run_featured_offer_prefetch
from app.parsers.enrich_scheduler import run_enrich_batch, start_enrich_scheduler
from app.parsers.catalog_filter_scheduler import start_catalog_filter_scheduler
from app.core.deals_channel import start_deals_channel_scheduler
from app.parsers.steam_catalog import enrich_game
from app.parsers.home_featured import (
    refresh_home_cache,
    cache_needs_refresh,
    _load_cache,
)
from app.parsers.steam_lists import (
    fetch_steam_list_slice,
    sync_steam_list_games,
    hydrate_steam_list_games,
    _list_spec,
)
from app.core.site_owner import is_site_owner, require_site_owner
from app.core.home_curation import (
    load_curation,
    save_curation,
    resolve_games_by_slugs,
    import_game_from_steam,
    ensure_game_cover,
    MAX_SPOTLIGHT,
)

app = FastAPI(
    title="KupujPL Games Discount Aggregator API",
    description="Backend API for gaming deals and discounts in Poland.",
    version="1.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


# region agent log
DEBUG_LOG_PATH = Path(__file__).resolve().parents[3] / "debug-c5be29.log"


def _agent_debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: dict) -> None:
    try:
        payload = {
            "sessionId": "c5be29",
            "runId": run_id,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        with DEBUG_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
# endregion


class CachedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200 and path.endswith(
            (".js", ".css", ".svg", ".png", ".ico", ".webmanifest", ".woff2")
        ):
            response.headers["Cache-Control"] = "public, max-age=86400"
        return response


app.mount("/static", CachedStaticFiles(directory=STATIC_DIR), name="static")


from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        path = request.url.path
        accepts_html = "text/html" in request.headers.get("accept", "")
        if accepts_html and not path.startswith(("/api", "/static")):
            return HTMLResponse(content=not_found_html(), status_code=404)
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _user_id_from_bearer(request: Request) -> int | None:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("bearer "):
        return None
    token = auth.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        return int(sub) if sub else None
    except Exception:
        return None


@app.middleware("http")
async def games_tracking_middleware(request: Request, call_next):
    if should_block_crawler_request(request):
        return Response(status_code=403, content="blocked")
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        if request.url.path.startswith("/api/"):
            # region agent log
            _agent_debug_log(
                "post-fix",
                "C",
                "app/main.py:games_tracking_middleware.exception",
                "API exception before response",
                {
                    "method": request.method,
                    "path": request.url.path,
                    "errorType": type(exc).__name__,
                    "message": str(exc)[:240],
                    "elapsedMs": elapsed_ms,
                },
            )
            # endregion
        raise
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    if request.url.path.startswith("/api/") and response.status_code >= 400:
        # region agent log
        _agent_debug_log(
            "pre-fix",
            "C",
            "app/main.py:games_tracking_middleware",
            "API non-2xx response",
            {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "elapsedMs": elapsed_ms,
            },
        )
        # endregion
    if request.method == "GET" and 200 <= response.status_code < 400:
        uid = _user_id_from_bearer(request)
        try:
            record_site_visit(
                request,
                uid,
                verified_human=False,
                human_verification="passive_get",
            )
        except Exception:
            pass
    if request.url.path.startswith("/api/") and 200 <= response.status_code < 400:
        uid = _user_id_from_bearer(request)
        if uid:
            try:
                touch_user_last_seen(uid)
            except Exception:
                pass
    return response


@app.post("/api/track-visit")
def track_client_visit(request: Request, body: TrackVisitRequest):
    """SPA page-view ping with JWT — records real screen + logged-in user."""
    path = (body.path or "").strip()
    if not path or len(path) > 480:
        raise HTTPException(status_code=400, detail="Invalid path")
    uid = _user_id_from_bearer(request)
    record_site_visit(
        request,
        uid,
        path=path,
        force=True,
        utm_source=body.utm_source,
        utm_medium=body.utm_medium,
        utm_campaign=body.utm_campaign,
        utm_term=body.utm_term,
        utm_content=body.utm_content,
        gclid=body.gclid,
        wbraid=body.wbraid,
        gbraid=body.gbraid,
        referrer_url=body.referrer_url,
        client_agent=body.client_agent,
        verified_human=True,
        human_verification="track_visit_js",
    )
    return {"ok": True}


@app.post("/api/track-heartbeat")
def track_client_heartbeat(request: Request, body: TrackVisitRequest | None = None):
    """Keep-alive ping for session duration while user stays on a page."""
    path = ((body.path if body else None) or "/").strip()
    if len(path) > 480:
        raise HTTPException(status_code=400, detail="Invalid path")
    uid = _user_id_from_bearer(request)
    client_agent = body.client_agent if body else None
    record_session_heartbeat(request, uid, path=path, client_agent=client_agent)
    return {"ok": True}


@app.post("/api/debug/price-log", include_in_schema=False)
async def debug_price_log(request: Request):
    """Temporary price-debug sink for this debug session."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict) or body.get("sessionId") != "c5be29":
        return {"ok": True}
    safe = {
        "runId": str(body.get("runId") or "")[:80],
        "hypothesisId": str(body.get("hypothesisId") or "")[:80],
        "location": str(body.get("location") or "")[:160],
        "message": str(body.get("message") or "")[:160],
        "data": body.get("data") if isinstance(body.get("data"), dict) else {},
        "timestamp": body.get("timestamp"),
    }
    logging.getLogger("price_debug").warning(
        "PRICE_DEBUG %s", json.dumps(safe, ensure_ascii=False, default=str)
    )
    return {"ok": True}


_PRICE_DEBUG_ENABLED = os.environ.get("PRICE_DEBUG", "0").lower() in ("1", "true", "yes")


def _price_debug_log(message: str, data: dict) -> None:
    # region agent log
    if not _PRICE_DEBUG_ENABLED:
        return
    try:
        payload = {
            "sessionId": "c5be29",
            "runId": "prices-server-pre-fix",
            "hypothesisId": "P1,P2,P3,P5",
            "location": "app/main.py:price-debug",
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        logging.getLogger("price_debug").warning(
            "PRICE_DEBUG %s", json.dumps(payload, ensure_ascii=False, default=str)
        )
    except Exception:
        pass
    # endregion


def _static_page(name: str):
    path = os.path.join(STATIC_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(path)


def _display_title(title: str | None) -> str:
    if not title:
        return ""
    return html_lib.unescape(title.strip())


def _normalize_shopping_region(region: str | None) -> str:
    r = (region or "pl").strip().lower()
    return "us" if r == "us" else "pl"


def _steam_shop_for_region(region: str) -> str:
    return "Steam US" if region == "us" else "Steam"


def _display_shops_for_region(region: str) -> set[str]:
    active = set(get_display_shops())
    if region == "us":
        active.discard("Steam")
        active.add("Steam US")
    else:
        active.discard("Steam US")
    return active


def _offer_activation_region(offer: Offer) -> str:
    raw = (getattr(offer, "activation_region", None) or "unknown").strip().lower()
    if raw in {"eu", "na", "global", "unknown"}:
        return raw
    return "unknown"


def _offer_visible_for_shopping_region(offer: Offer, region: str) -> bool:
    """Filter keyshop rows by activation region for PL vs US shoppers."""
    region = _normalize_shopping_region(region)
    act = _offer_activation_region(offer)
    shop = (offer.shop_name or "").strip()
    if shop == "Steam US":
        return region == "us"
    if shop == "Steam":
        return region != "us"
    if act == "unknown":
        return True
    if region == "us":
        return act in {"na", "global"}
    return act in {"eu", "global"}


def _best_offers_map(
    db: Session,
    game_ids: list[int],
    *,
    region: str = "pl",
) -> dict[int, Offer]:
    if not game_ids:
        return {}
    region = _normalize_shopping_region(region)
    active = _display_shops_for_region(region)
    steam_shop = _steam_shop_for_region(region)
    steam_map = _steam_offers_map(
        db,
        game_ids,
        shop_name=steam_shop,
        fallback_shop="Steam" if region == "us" else None,
    )
    offers = (
        db.query(Offer)
        .filter(
            Offer.game_id.in_(game_ids),
            Offer.in_stock == True,
            Offer.shop_name.in_(active),
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
        )
        .all()
    )
    best: dict[int, Offer] = {}
    for offer in offers:
        if not _offer_visible_for_shopping_region(offer, region):
            continue
        steam = steam_map.get(offer.game_id)
        steam_price = float(steam.price_pln) if steam and steam.price_pln else None
        if not offer_eligible_for_best_price(offer, steam_price_pln=steam_price):
            continue
        prev = best.get(offer.game_id)
        if prev is None or offer.price_pln < prev.price_pln:
            best[offer.game_id] = offer
    return best


def _steam_offers_map(
    db: Session,
    game_ids: list[int],
    shop_name: str = "Steam",
    *,
    fallback_shop: str | None = None,
) -> dict[int, Offer]:
    if not game_ids:
        return {}
    names = [shop_name]
    if fallback_shop and fallback_shop != shop_name:
        names.append(fallback_shop)
    offers = (
        db.query(Offer)
        .filter(
            Offer.game_id.in_(game_ids),
            Offer.shop_name.in_(names),
            Offer.in_stock == True,
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
        )
        .all()
    )
    primary: dict[int, Offer] = {}
    fallback: dict[int, Offer] = {}
    for offer in offers:
        target = primary if offer.shop_name == shop_name else fallback
        prev = target.get(offer.game_id)
        if prev is None or offer.price_pln < prev.price_pln:
            target[offer.game_id] = offer
    if not fallback_shop:
        return primary
    out = dict(primary)
    for gid, offer in fallback.items():
        if gid not in out:
            out[gid] = offer
    return out


def _savings_vs_steam(best: Offer | None, steam: Offer | None) -> dict[str, float | int | None]:
    steam_price = float(steam.price_pln) if steam and steam.price_pln else None
    best_price = float(best.price_pln) if best and best.price_pln else None
    if steam_price is None or best_price is None or best_price >= steam_price:
        return {"steam_price_pln": steam_price, "savings_pln": None, "savings_pct": None}
    savings = steam_price - best_price
    if savings < 0.01:
        return {"steam_price_pln": steam_price, "savings_pln": None, "savings_pct": None}
    return {
        "steam_price_pln": steam_price,
        "savings_pln": round(savings, 2),
        "savings_pct": int(round((savings / steam_price) * 100)),
    }


def _game_list_item(
    game: Game,
    best: Offer | None,
    steam: Offer | None = None,
    *,
    deal_age_label: str | None = None,
) -> GameListResponse:
    savings = _savings_vs_steam(best, steam)
    best_price = best.price_pln if best else None
    label = lowest_ever_label_pl(game, best_price)
    return GameListResponse(
        id=game.id,
        title=_display_title(game.title),
        slug=game.slug,
        cover_image=list_cover_image(game.cover_image, game.steam_appid),
        steam_appid=game.steam_appid,
        release_date=game.release_date,
        rating=game.rating,
        best_price_pln=best_price,
        best_price_is_official=best.is_official if best else None,
        best_shop_name=best.shop_name if best else None,
        steam_price_pln=savings["steam_price_pln"],
        savings_pln=savings["savings_pln"],
        savings_pct=savings["savings_pct"],
        lowest_ever_pln=game.lowest_ever_pln,
        avg_best_price_30d=game.avg_best_price_30d,
        lowest_ever_label=label,
        at_historical_low=bool(label),
        deal_age_label=deal_age_label,
        is_free=bool(game.is_free) or (best_price is not None and best_price <= 0.01),
    )


def _sorted_offers(game: Game, *, region: str = "pl") -> list[Offer]:
    region = _normalize_shopping_region(region)
    active = _display_shops_for_region(region)
    visible = [
        o for o in game.offers
        if o.in_stock
        and o.shop_name in active
        and o.price_pln is not None
        and o.price_pln > 0
        and _offer_visible_for_shopping_region(o, region)
    ]
    # One row per shop: cheapest among matching activation regions
    by_shop: dict[str, Offer] = {}
    for offer in visible:
        prev = by_shop.get(offer.shop_name)
        if prev is None or offer.price_pln < prev.price_pln:
            by_shop[offer.shop_name] = offer
    return sorted(
        by_shop.values(),
        key=lambda o: o.price_pln if o.price_pln is not None else float("inf"),
    )


def _offers_updated_at(game: Game) -> datetime | None:
    in_stock = [o for o in game.offers if o.in_stock]
    if not in_stock:
        return None
    latest = max((o.updated_at or datetime.min for o in in_stock), default=None)
    if latest is None or latest == datetime.min:
        return None
    if latest.tzinfo:
        latest = latest.replace(tzinfo=None)
    return latest


def _offers_stale(game: Game) -> bool:
    return game_needs_offer_refresh(game)


def _in_stock_shop_count(game: Game, *, region: str = "pl") -> int:
    region = _normalize_shopping_region(region)
    active = _display_shops_for_region(region)
    return len({
        o.shop_name for o in game.offers
        if o.in_stock
        and o.shop_name in active
        and o.price_pln is not None
        and o.price_pln > 0
        and _offer_visible_for_shopping_region(o, region)
    })


def _should_queue_offer_refresh(game: Game, *, force: bool = False) -> bool:
    if force:
        return True
    if _in_stock_shop_count(game) == 0:
        return True
    if is_in_tier_a_daily_scan(game):
        return False
    return game_needs_offer_refresh(game)


def _queue_offer_refresh(
    background_tasks: BackgroundTasks,
    game: Game,
    *,
    force: bool = False,
) -> None:
    background_tasks.add_task(
        refresh_offers_for_game,
        game.id,
        force=force,
        fill_missing=True,
        fast=False,
    )


def _offer_to_response(offer: Offer) -> OfferResponse:
    confidence = offer.match_confidence
    low = confidence is not None and confidence < 0.55
    trust = shop_trust_badge(offer.shop_name, is_official=offer.is_official)
    return OfferResponse(
        id=offer.id,
        game_id=offer.game_id,
        shop_name=offer.shop_name,
        price_pln=offer.price_pln,
        original_price_pln=offer.original_price_pln,
        affiliate_url=make_affiliate_link(offer.affiliate_url, offer.shop_name),
        is_official=offer.is_official,
        in_stock=offer.in_stock,
        activation_region=_offer_activation_region(offer),
        updated_at=offer.updated_at,
        match_confidence=confidence,
        low_confidence=low,
        trust_label=trust["label"] if trust else None,
        trust_tier=trust["tier"] if trust else None,
        trust_note=trust.get("notes_pl") if trust else None,
        refund_policy_url=trust.get("refund_policy_url") if trust else None,
        refund_note_pl=trust.get("refund_note_pl") if trust else None,
        refund_note_uk=trust.get("refund_note_uk") if trust else None,
    )


def _game_to_response(
    game: Game,
    *,
    related_dlc: list[GameListResponse] | None = None,
    parent_game: GameListResponse | None = None,
    region: str = "pl",
) -> GameResponse:
    region = _normalize_shopping_region(region)
    sorted_offers = _sorted_offers(game, region=region)
    offers = [_offer_to_response(o) for o in sorted_offers]
    updated_at = _offers_updated_at(game)
    tier_a = is_in_tier_a_daily_scan(game)
    best_raw = sorted_offers[0] if sorted_offers else None
    best_price = best_raw.price_pln if best_raw else None
    steam_shop = _steam_shop_for_region(region)
    steam_offer = next(
        (o for o in game.offers if o.shop_name == steam_shop and o.in_stock),
        None,
    )
    if steam_offer is None and region == "us":
        steam_offer = next(
            (o for o in game.offers if o.shop_name == "Steam" and o.in_stock),
            None,
        )
    savings = _savings_vs_steam(best_raw, steam_offer)
    label = lowest_ever_label_pl(game, best_price)
    return GameResponse(
        id=game.id,
        title=_display_title(game.title),
        slug=game.slug,
        cover_image=game.cover_image,
        description=game.description,
        steam_appid=game.steam_appid,
        release_date=game.release_date,
        rating=game.rating,
        created_at=game.created_at,
        offers=offers,
        offers_updated_at=updated_at,
        offers_stale=_offers_stale(game),
        in_stock_shop_count=_in_stock_shop_count(game, region=region),
        in_tier_a_daily_scan=tier_a,
        next_tier_a_scan_at=next_tier_a_scan_at() if tier_a else None,
        lowest_ever_pln=game.lowest_ever_pln,
        avg_best_price_30d=game.avg_best_price_30d,
        lowest_ever_label=label,
        at_historical_low=bool(label),
        steam_price_pln=savings["steam_price_pln"],
        savings_pln=savings["savings_pln"],
        savings_pct=savings["savings_pct"],
        is_free=bool(game.is_free),
        related_dlc=related_dlc or [],
        parent_game=parent_game,
    )


def _spotlight_game_responses(db: Session, slugs: list[str]) -> list[GameListResponse]:
    games = resolve_games_by_slugs(db, slugs)
    if not games:
        return []
    for game in games:
        ensure_game_cover(db, game)
    game_ids = [g.id for g in games]
    best_map = _best_offers_map(db, game_ids)
    steam_map = _steam_offers_map(db, game_ids)
    by_slug = {g.slug: g for g in games}
    out: list[GameListResponse] = []
    for slug in slugs:
        game = by_slug.get(slug)
        if not game:
            continue
        out.append(_game_list_item(game, best_map.get(game.id), steam_map.get(game.id)))
    return out


def _curation_response(db: Session) -> HomeCurationResponse:
    data = load_curation()
    slugs = data.get("spotlight_slugs") or []
    games = resolve_games_by_slugs(db, slugs)
    game_ids = [g.id for g in games]
    for game in games:
        ensure_game_cover(db, game)
    best_map = _best_offers_map(db, game_ids)
    steam_map = _steam_offers_map(db, game_ids)
    by_slug = {g.slug: g for g in games}
    items: list[HomeCurationGameResponse] = []
    for slug in slugs:
        game = by_slug.get(slug)
        if not game:
            continue
        base = _game_list_item(game, best_map.get(game.id), steam_map.get(game.id))
        items.append(
            HomeCurationGameResponse(
                **base.model_dump(),
                in_stock_shop_count=_in_stock_shop_count(game),
            )
        )
    return HomeCurationResponse(
        spotlight_slugs=slugs,
        updated_at=data.get("updated_at"),
        games=items,
    )


def _find_game_by_slug(db: Session, slug: str, *, create_stub: bool = False) -> Game | None:
    game = resolve_game_slug(db, slug)
    if game or not create_stub:
        return game
    appid = _steam_appid_from_slug_suffix(slug)
    if appid is None:
        return None
    try:
        game = upsert_game_stub(db, appid, f"Gra {appid}", None)
        db.commit()
        return db.query(Game).filter(Game.id == game.id).first()
    except Exception:
        db.rollback()
        return db.query(Game).filter(Game.steam_appid == appid).first()


def _load_game_with_offers(db: Session, game_id: int) -> Game | None:
    return (
        db.query(Game)
        .options(joinedload(Game.offers))
        .filter(Game.id == game_id)
        .first()
    )


@app.on_event("startup")
def on_startup():
    init_db()

    def _refresh_home_if_stale():
        if not cache_needs_refresh():
            return
        db = SessionLocal()
        try:
            refresh_home_cache(db)
        except Exception as exc:
            logging.getLogger("startup").warning("Home cache refresh failed: %s", exc)
        finally:
            db.close()

    def _cleanup_stubs_once():
        db = SessionLocal()
        try:
            stats = cleanup_mistaken_stub_games(db)
            if stats["removed"]:
                logging.getLogger("startup").info("Cleaned mistaken stub games: %s", stats)
        except Exception as exc:
            logging.getLogger("startup").warning("Stub cleanup failed: %s", exc)
        finally:
            db.close()

    def _refresh_visible_count():
        db = SessionLocal()
        try:
            count = refresh_visible_games_count_cache(db)
            logging.getLogger("startup").info("Visible games count cached: %s", count)
        except Exception as exc:
            logging.getLogger("startup").warning("Visible games count refresh failed: %s", exc)
        finally:
            db.close()

    import threading
    threading.Thread(target=_refresh_home_if_stale, daemon=True).start()
    threading.Thread(target=_cleanup_stubs_once, daemon=True).start()
    threading.Thread(target=_refresh_visible_count, daemon=True).start()
    start_enrich_scheduler()
    start_catalog_filter_scheduler()
    start_offer_scheduler()
    start_deals_channel_scheduler()


@app.get("/favicon.ico", include_in_schema=False)
def favicon_ico():
    return FileResponse(os.path.join(STATIC_DIR, "favicon.ico"), media_type="image/x-icon")


@app.get("/sw.js", include_in_schema=False)
def service_worker_js():
    sw_path = os.path.join(STATIC_DIR, "sw.js")
    with open(sw_path, encoding="utf-8") as f:
        body = f.read()
    return Response(
        content=body,
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"},
    )


@app.get("/")
def read_root():
    return _static_page("index.html")


@app.get("/login")
def login_page():
    return _static_page("login.html")


@app.get("/register")
def register_page():
    return _static_page("register.html")


@app.get("/forgot-password")
def forgot_password_page():
    return _static_page("forgot-password.html")


@app.get("/reset-password")
def reset_password_page():
    return _static_page("reset-password.html")


@app.get("/regulamin")
def regulamin_page():
    return _static_page("regulamin.html")


@app.get("/polityka-prywatnosci")
def privacy_page():
    return _static_page("polityka-prywatnosci.html")


@app.get("/o-nas")
def about_page():
    return _static_page("o-nas.html")


@app.get("/kontakt")
def contact_page():
    return _static_page("kontakt.html")


@app.get("/wsparcie")
def support_page():
    return _static_page("wsparcie.html")


@app.get("/legal-en")
def legal_en_page():
    return _static_page("legal-en.html")


@app.get("/api/site/info")
def site_info():
    return public_site_info()


@app.get("/api/geo")
def api_geo(request: Request):
    """Visitor country for region UX (Cloudflare / forwarded headers)."""
    from app.core.site_tracking import visitor_geo_hint

    return visitor_geo_hint(request)


@app.get("/api/fx")
def api_fx():
    """NBP mid rates for approximate USD display next to PLN."""
    from app.parsers.currency_pln import fx_snapshot

    return fx_snapshot()


@app.get("/api/health")
def api_health():
    return {"ok": True, "service": "kupujpl-games"}


@app.get("/robots.txt", response_class=Response)
def robots():
    return Response(content=robots_txt(), media_type="text/plain; charset=utf-8")


@app.get("/google2e455d73d8350b86.html", response_class=Response)
def google_site_verification_file():
    path = os.path.join(STATIC_DIR, "google2e455d73d8350b86.html")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="text/html; charset=utf-8")


@app.get("/sitemap.xml", response_class=Response)
def sitemap_index(db: Session = Depends(get_db)):
    return Response(content=sitemap_index_xml(), media_type="application/xml; charset=utf-8")


@app.get("/sitemap-games.xml", response_class=Response)
def sitemap_games(db: Session = Depends(get_db)):
    return Response(content=sitemap_games_xml(db), media_type="application/xml; charset=utf-8")


@app.get("/sitemap-categories.xml", response_class=Response)
def sitemap_categories(db: Session = Depends(get_db)):
    return Response(content=sitemap_categories_xml(db), media_type="application/xml; charset=utf-8")


@app.get("/sitemap-deals.xml", response_class=Response)
def sitemap_deals(db: Session = Depends(get_db)):
    return Response(content=sitemap_deals_xml(db), media_type="application/xml; charset=utf-8")


@app.get("/sitemap-blog.xml", response_class=Response)
def sitemap_blog():
    return Response(content=sitemap_blog_xml(), media_type="application/xml; charset=utf-8")


def _game_landing_context(db: Session, game: Game) -> dict:
    game = _load_game_with_offers(db, game.id)
    best_map = _best_offers_map(db, [game.id])
    steam_map = _steam_offers_map(db, [game.id])
    best = best_map.get(game.id)
    steam = steam_map.get(game.id)
    savings = _savings_vs_steam(best, steam)
    offers = [_offer_to_response(o) for o in _sorted_offers(game)]
    history = get_price_history(db, game.id, days=90)
    return {
        "game": game,
        "offers": offers,
        "best": best,
        "steam": steam,
        "savings": savings,
        "history": history,
        "cover": list_cover_image(game.cover_image, game.steam_appid),
    }


@app.get("/gra/{slug}", response_class=HTMLResponse)
def game_landing_page(slug: str, db: Session = Depends(get_db)):
    game = _find_game_by_slug(db, slug, create_stub=False)
    if not game:
        raise HTTPException(status_code=404, detail="Gra nie znaleziona")
    ctx = _game_landing_context(db, game)
    best_price = ctx["best"].price_pln if ctx["best"] else None
    label = lowest_ever_label_pl(ctx["game"], best_price)
    dlc_games = related_dlc_games(db, ctx["game"], limit=8)
    dlc_ids = [g.id for g in dlc_games]
    parent_row = parent_game_for_dlc(db, ctx["game"])
    parent_ids = [parent_row.id] if parent_row else []
    map_ids = dlc_ids + parent_ids
    dlc_best = _best_offers_map(db, map_ids) if map_ids else {}
    dlc_steam = _steam_offers_map(db, map_ids) if map_ids else {}
    related = [
        _game_list_item(g, dlc_best.get(g.id), dlc_steam.get(g.id)).model_dump()
        for g in dlc_games
    ]
    parent_dump = None
    if parent_row:
        parent_dump = _game_list_item(
            parent_row, dlc_best.get(parent_row.id), dlc_steam.get(parent_row.id)
        ).model_dump()
    return HTMLResponse(
        game_interactive_html(
            title=_display_title(ctx["game"].title),
            slug=ctx["game"].slug,
            description=ctx["game"].description,
            cover_image=ctx["cover"],
            best_price_pln=best_price,
            best_shop_name=ctx["best"].shop_name if ctx["best"] else None,
            steam_price_pln=ctx["savings"].get("steam_price_pln"),
            savings_pln=ctx["savings"].get("savings_pln"),
            savings_pct=ctx["savings"].get("savings_pct"),
            offers=ctx["offers"],
            history=ctx["history"],
            lowest_ever_pln=ctx["game"].lowest_ever_pln,
            avg_best_price_30d=ctx["game"].avg_best_price_30d,
            lowest_ever_label=label,
            at_historical_low=bool(label),
            related_dlc=related,
            parent_game=parent_dump,
            indexable=ctx["best"] is not None,
        )
    )


@app.get("/og/logo.png")
def brand_logo_image():
    png = render_logo_png()
    if not png:
        return RedirectResponse(url=f"{SITE_ORIGIN}/static/favicon.png?v=1", status_code=302)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=604800"},
    )


@app.get("/og/gra/{slug}.png")
def game_og_image(slug: str, db: Session = Depends(get_db)):
    game = _find_game_by_slug(db, slug, create_stub=False)
    if not game:
        raise HTTPException(status_code=404, detail="Gra nie znaleziona")
    best = _best_offers_map(db, [game.id]).get(game.id)
    cover = list_cover_image(game.cover_image, game.steam_appid)
    if best and best.price_pln:
        price_text = f"Od {best.price_pln:.2f} zł".replace(".", ",")
    else:
        price_text = "Porównaj ceny w sklepach"
    png = render_og_png(game.slug, game.title, price_text, cover)
    if not png:
        return RedirectResponse(url=cover or f"{SITE_ORIGIN}/static/favicon.ico", status_code=302)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=43200"},
    )


@app.get("/najtaniej/{slug}")
def najtaniej_alias(slug: str):
    return RedirectResponse(url=f"{SITE_ORIGIN}/gra/{slug}", status_code=301)


@app.get("/historia-cen/{slug}", response_class=HTMLResponse)
def price_history_page(slug: str, db: Session = Depends(get_db)):
    game = _find_game_by_slug(db, slug, create_stub=False)
    if not game:
        raise HTTPException(status_code=404, detail="Gra nie znaleziona")
    history = get_price_history(db, game.id, days=90)
    if len(history) < 30:
        return RedirectResponse(url=f"{SITE_ORIGIN}/gra/{slug}", status_code=302)
    ctx = _game_landing_context(db, game)
    return HTMLResponse(
        price_history_landing_html(
            title=game.title,
            slug=game.slug,
            cover_image=ctx["cover"],
            history=history,
            lowest_ever_pln=game.lowest_ever_pln,
            avg_best_price_30d=game.avg_best_price_30d,
            best_price_pln=ctx["best"].price_pln if ctx["best"] else None,
        )
    )


@app.get("/kategoria/{slug}", response_class=HTMLResponse)
def category_landing_page(slug: str, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.slug == slug).first()
    if not cat:
        raise HTTPException(status_code=404, detail="Kategoria nie znaleziona")
    game_ids_q = (
        db.query(game_categories.c.game_id)
        .filter(game_categories.c.category_id == cat.id)
    )
    games = (
        exclude_hidden_games_query(db.query(Game))
        .filter(Game.id.in_(game_ids_q))
        .limit(48)
        .all()
    )
    gids = [g.id for g in games]
    best_map = _best_offers_map(db, gids)
    steam_map = _steam_offers_map(db, gids)
    items = [_game_list_item(g, best_map.get(g.id), steam_map.get(g.id)) for g in games]
    return HTMLResponse(category_landing_html(category=cat, games=items))


@app.get("/promocje", response_class=HTMLResponse)
def promocje_page(db: Session = Depends(get_db)):
    return HTMLResponse(_deals_page_html(db, kind="promocje"))


@app.get("/najwieksze-okazje", response_class=HTMLResponse)
def najwieksze_okazje_page(db: Session = Depends(get_db)):
    return HTMLResponse(_deals_page_html(db, kind="okazje"))


@app.get("/gry-ponizej-{price}-zl", response_class=HTMLResponse)
def gry_ponizej_page(price: int, db: Session = Depends(get_db)):
    if price not in (20, 50, 100):
        raise HTTPException(status_code=404, detail="Nie znaleziono")
    return HTMLResponse(_deals_page_html(db, kind="budget", max_price=price))


@app.get("/blog", response_class=HTMLResponse)
def blog_index():
    return HTMLResponse(blog_index_html())


@app.get("/blog/{slug}", response_class=HTMLResponse)
def blog_post(slug: str):
    html = blog_landing_html(slug)
    if not html:
        raise HTTPException(status_code=404, detail="Artykuł nie znaleziony")
    return HTMLResponse(html)


def _deals_page_html(db: Session, *, kind: str, max_price: int | None = None) -> str:
    candidate_ids = [
        row[0]
        for row in db.query(Offer.game_id)
        .filter(Offer.in_stock.is_(True), Offer.price_pln > 0)
        .distinct()
        .limit(400)
        .all()
    ]
    games = (
        exclude_hidden_games_query(db.query(Game))
        .filter(Game.id.in_(candidate_ids))
        .all()
    )
    gids = [g.id for g in games]
    best_map = _best_offers_map(db, gids)
    steam_map = _steam_offers_map(db, gids)
    items: list[GameListResponse] = []
    for game in games:
        best = best_map.get(game.id)
        if not best:
            continue
        item = _game_list_item(game, best, steam_map.get(game.id))
        if kind == "budget" and max_price and (item.best_price_pln or 9999) > max_price:
            continue
        if kind == "okazje" and (item.savings_pct or 0) < 10:
            continue
        if kind == "promocje" and (item.savings_pct or 0) < 5:
            continue
        items.append(item)
    items.sort(key=lambda x: (x.savings_pct or 0, -(x.best_price_pln or 9999)), reverse=True)
    return deals_landing_html(kind=kind, games=items[:60], max_price=max_price)


@app.get("/share/{slug}")
def share_redirect(slug: str):
    return RedirectResponse(url=f"{SITE_ORIGIN}/gra/{slug}", status_code=302)


@app.get("/wykop-callback", response_class=HTMLResponse)
def wykop_callback(rtoken: Optional[str] = Query(None)):
    """Adres zwrotny Wykop Connect — zapisuje rtoken dla kupujpl-promo."""
    if not rtoken:
        return HTMLResponse(callback_html(rtoken=None, saved=False, error="Brak parametru rtoken w URL."), status_code=400)
    saved = save_refresh_token(rtoken)
    return HTMLResponse(callback_html(rtoken=rtoken, saved=saved, error=None if saved else "Nie udało się zapisać tokenu na serwerze."))


@app.get("/panel")
def panel_page():
    return _static_page("panel.html")


@app.get("/panel2")
def panel2_redirect():
    return RedirectResponse(url="/games/panel3", status_code=301)


@app.get("/panel3")
def panel3_page(request: Request):
    if not panel3_gate_ok(request):
        return _static_page("panel3_gate.html")
    return _static_page("panel3.html")


@app.post("/panel3/unlock")
async def panel3_unlock(request: Request):
    body = await request.body()
    params = parse_qs(body.decode("utf-8", errors="replace"))
    code = str((params.get("access_code") or [""])[0])
    from app.core.panel3_auth import _unlock_code_ok

    if not _unlock_code_ok(code):
        return RedirectResponse(url="/games/panel3?err=1", status_code=303)
    response = RedirectResponse(url="/games/panel3", status_code=303)
    response.set_cookie(PANEL3_COOKIE_NAME, panel3_cookie_value(), **panel3_cookie_kwargs(request))
    return response


@app.get("/panel3/logout")
def panel3_logout(request: Request):
    response = RedirectResponse(url="/games/panel3", status_code=303)
    response.delete_cookie(PANEL3_COOKIE_NAME, **panel3_cookie_kwargs(request))
    return response


@app.get("/panel3/live")
def panel3_live_page(request: Request):
    if not panel3_gate_ok(request):
        return RedirectResponse(url="/games/panel3", status_code=303)
    return _static_page("panel_live.html")


@app.get("/api/admin/stats")
def admin_stats(request: Request, db: Session = Depends(get_db)):
    require_panel3_gate(request)
    return collect_admin_stats(db)


@app.get("/api/admin/events")
def admin_events(
    request: Request,
    last_user_id: int = Query(0, ge=0),
    last_visit_id: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    require_panel3_gate(request)
    return collect_admin_events(db, last_user_id=last_user_id, last_visit_id=last_visit_id)


@app.get("/api/admin/live")
def admin_live(request: Request, db: Session = Depends(get_db)):
    require_panel3_gate(request)
    return collect_live_dashboard(db)


@app.get("/api/admin/affiliate-feeds")
def admin_affiliate_feeds_status(request: Request):
    require_panel3_admin(request)
    from app.parsers.affiliate_feeds import affiliate_feed_status

    return {"ok": True, **affiliate_feed_status()}


@app.post("/api/admin/affiliate-feeds/refresh")
def admin_affiliate_feeds_refresh(request: Request):
    require_panel3_admin(request)
    from app.parsers.affiliate_feeds import affiliate_feed_status, refresh_affiliate_feeds

    rows = refresh_affiliate_feeds(force=True)
    return {"ok": True, "rows": rows, "status": affiliate_feed_status()}


@app.get("/api/admin/affiliate-config")
def admin_affiliate_config(request: Request):
    require_panel3_admin(request)
    return {"ok": True, **affiliate_env_status()}


@app.get("/api/go/{offer_id}")
def affiliate_go_redirect(
    offer_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    from app.models.models import Offer

    offer = (
        db.query(Offer)
        .options(joinedload(Offer.game))
        .filter(Offer.id == offer_id, Offer.in_stock.is_(True))
        .first()
    )
    if not offer or not offer.game:
        raise HTTPException(status_code=404, detail="Offer not found")
    # Unwrap Awin (awin1.com) server-side → shop URL + awc= so ad blockers
    # do not kill the buy click in the browser.
    destination = resolve_outbound_url(offer.affiliate_url, offer.shop_name)
    log_affiliate_click(
        db,
        offer=offer,
        game=offer.game,
        destination_url=destination,
        request=request,
    )
    return RedirectResponse(url=destination, status_code=302)


@app.get("/api/shop-config")
def get_shop_config():
    return get_scan_shops_config()


@app.get("/api/admin/scan-shops")
def admin_get_scan_shops(request: Request):
    require_panel3_admin(request)
    return {"ok": True, **get_scan_shops_config()}


@app.post("/api/admin/scan-shops")
async def admin_set_scan_shops(request: Request):
    require_panel3_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")
    if "shop" in body and "enabled" in body:
        shop = str(body.get("shop") or "").strip()
        enabled = bool(body.get("enabled"))
        try:
            toggle_scan_shop(shop, enabled=enabled)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif "disabled" in body:
        disabled = body.get("disabled") or []
        if not isinstance(disabled, list):
            raise HTTPException(status_code=400, detail="disabled must be a list")
        reasons = body.get("reason") if isinstance(body.get("reason"), dict) else None
        save_disabled_scan_shops(disabled, reasons=reasons)
    else:
        raise HTTPException(status_code=400, detail="Provide {shop, enabled} or {disabled: [...]}")
    return {"ok": True, **get_scan_shops_config()}


@app.get("/api/admin/scan-routing")
def admin_get_scan_routing(request: Request):
    require_panel3_admin(request)
    return {"ok": True, **get_scan_routing_config()}


@app.post("/api/admin/scan-routing")
async def admin_set_scan_routing(request: Request):
    require_panel3_admin(request)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")
    try:
        if "shop" in body and "worker" in body:
            set_shop_worker(str(body.get("shop") or "").strip(), str(body.get("worker") or "").strip())
        elif "routing" in body and isinstance(body.get("routing"), dict):
            save_scan_routing(body["routing"])
        else:
            raise HTTPException(status_code=400, detail="Provide {shop, worker} or {routing: {...}}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **get_scan_routing_config()}


@app.get("/api/admin/tier-a/status")
def admin_tier_a_status(request: Request):
    require_panel3_admin(request)
    return get_tier_a_status()


@app.post("/api/admin/tier-a/laptop-state")
async def admin_tier_a_laptop_state(request: Request):
    """Laptop worker pushes scan progress to VPS."""
    require_panel3_admin(request)
    from app.parsers.tier_a_scan_state import clear_worker_cancel, save_laptop_state
    from app.parsers.tier_a_auto_scan import is_auto_scan_paused

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")
    manual_force = bool(body.get("manual_force"))
    if manual_force and body.get("phase") == "scan_keyshops":
        clear_worker_cancel("laptop")
    if is_auto_scan_paused() and body.get("phase") == "scan_keyshops" and not manual_force:
        body = {
            "worker": "laptop",
            "phase": "stopped",
            "current_game": None,
            "scan_subphase": None,
            "eta_sec": None,
            "games_per_min": None,
            "pause_remaining_sec": None,
        }
    if body.get("phase") in ("scan_keyshops", "done", "stopped") and (
        body.get("started_at") or body.get("finished_at") or body.get("stopped_at")
    ):
        clear_worker_cancel("laptop")
    state = save_laptop_state(body)
    return {"ok": True, "games_done": state.get("games_done"), "phase": state.get("phase")}


@app.post("/api/admin/tier-a/pc-state")
async def admin_tier_a_pc_state(request: Request):
    """Dev PC worker pushes CDKeys scan progress to VPS."""
    require_panel3_admin(request)
    from app.parsers.tier_a_scan_state import clear_worker_cancel, save_pc_state
    from app.parsers.tier_a_auto_scan import is_auto_scan_paused

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object")
    manual_force = bool(body.get("manual_force"))
    if manual_force and body.get("phase") == "scan_cdkeys":
        clear_worker_cancel("pc")
    if is_auto_scan_paused() and body.get("phase") == "scan_cdkeys" and not manual_force:
        body = {
            "worker": "pc",
            "phase": "stopped",
            "current_game": None,
            "scan_subphase": None,
            "eta_sec": None,
            "games_per_min": None,
            "pause_remaining_sec": None,
        }
    if body.get("phase") in ("scan_cdkeys", "done", "stopped") and (
        body.get("started_at") or body.get("finished_at") or body.get("stopped_at")
    ):
        clear_worker_cancel("pc")
    state = save_pc_state(body)
    return {"ok": True, "games_done": state.get("games_done"), "phase": state.get("phase")}


@app.post("/api/admin/tier-a/scan-vps")
def admin_tier_a_scan_vps(request: Request, background_tasks: BackgroundTasks):
    """Manual trigger: Tier A official-shop scan on VPS (Steam, GOG, Epic)."""
    require_panel3_admin(request)
    from app.parsers.daily_tier_a_pipeline import run_daily_tier_a_pipeline
    from app.parsers.tier_a_scan_state import clear_vps_cancel, load_vps_state

    vps = load_vps_state()
    phase = str(vps.get("phase") or "idle")
    if phase in ("rebuild_list", "scan_official"):
        raise HTTPException(status_code=409, detail="VPS Tier A scan already running")

    clear_vps_cancel()

    def _job() -> None:
        try:
            run_daily_tier_a_pipeline(force=True)
        except Exception as exc:
            logging.getLogger(__name__).exception("Tier A VPS manual scan failed: %s", exc)

    background_tasks.add_task(_job)
    return {"ok": True, "message": "VPS Tier A scan started"}


@app.post("/api/admin/tier-a/stop-vps")
def admin_tier_a_stop_vps(request: Request):
    """Request stop of the running VPS Tier A scan (checked between games)."""
    require_panel3_admin(request)
    from app.parsers.tier_a_scan_state import stop_vps_scan

    return stop_vps_scan()


@app.post("/api/admin/tier-a/stop-local")
def admin_tier_a_stop_local(request: Request):
    """Request stop of laptop/PC Tier A workers (checked by local workers)."""
    require_panel3_admin(request)
    from app.parsers.tier_a_scan_state import stop_local_scans

    return stop_local_scans()


@app.post("/api/admin/tier-a/pause-auto")
async def admin_tier_a_pause_auto(request: Request):
    """Pause all scheduled Tier A auto-scans (manual force still works)."""
    require_panel3_admin(request)
    from app.parsers.tier_a_auto_scan import set_auto_scan_paused

    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = str((body or {}).get("reason") or "paused from admin")
    by = str((body or {}).get("by") or "admin")
    state = set_auto_scan_paused(True, reason=reason, by=by)
    return {"ok": True, **state}


@app.post("/api/admin/tier-a/resume-auto")
async def admin_tier_a_resume_auto(request: Request):
    """Re-enable scheduled Tier A auto-scans."""
    require_panel3_admin(request)
    from app.parsers.tier_a_auto_scan import set_auto_scan_paused

    try:
        body = await request.json()
    except Exception:
        body = {}
    by = str((body or {}).get("by") or "admin")
    state = set_auto_scan_paused(False, by=by)
    return {"ok": True, **state}


@app.get("/api/admin/offers/queue")
def admin_offer_queue(
    request: Request,
    db: Session = Depends(get_db),
    limit: int = Query(60, ge=1, le=5000),
    tier: str | None = Query(None, description="top5000 for Tier A daily list"),
):
    """Games needing offer refresh — for local PC worker."""
    require_panel3_admin(request)
    if tier == "top5000":
        return {"items": build_tier_a_queue(db, limit=limit), "limit": limit, "tier": tier}
    return {"items": build_offer_queue(db, limit=limit), "limit": limit}


@app.post("/api/admin/offers/bulk")
def admin_offer_bulk(
    request: Request,
    body: RemoteOfferBulkRequest,
    db: Session = Depends(get_db),
):
    """Upload offers fetched on home PC (residential IP)."""
    require_panel3_admin(request)
    payload = [
        {
            "game_id": u.game_id,
            "offers": [o.model_dump() for o in u.offers],
        }
        for u in body.updates
    ]
    return apply_bulk_offers(db, payload, source=body.source)


@app.get("/designs")
def design_samples_page():
    return _static_page("design-samples/index.html")


@app.get("/layouts")
def layout_samples_page():
    return _static_page("layout-samples/index.html")


@app.post("/api/auth/register", response_model=TokenResponse)
def register(body: UserRegister, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        if existing.google_sub and getattr(existing, "auth_provider", "local") == "google":
            raise HTTPException(
                status_code=400,
                detail="Ten e-mail jest już zarejestrowany przez Google. Użyj przycisku „Kontynuuj z Google”.",
            )
        raise HTTPException(status_code=400, detail="Ten adres e-mail jest już zarejestrowany")

    user = User(email=email, hashed_password=get_password_hash(body.password), auth_provider="local")
    db.add(user)
    db.commit()
    db.refresh(user)
    user.last_seen_at = datetime.utcnow()
    db.commit()

    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user=UserResponse.from_user(user),
    )


@app.get("/api/auth/google-config", response_model=GoogleAuthConfigResponse)
def google_auth_config():
    cid = google_client_id()
    return GoogleAuthConfigResponse(enabled=google_auth_enabled(), client_id=cid)


@app.post("/api/auth/google", response_model=TokenResponse)
def auth_google(body: GoogleAuthRequest, db: Session = Depends(get_db)):
    idinfo = verify_google_credential(body.credential.strip())
    user, _is_new = authenticate_google_user(db, idinfo)
    token = issue_token_for_user(db, user)
    return TokenResponse(access_token=token, user=UserResponse.from_user(user))


@app.post("/api/auth/login", response_model=TokenResponse)
def login(body: UserLogin, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(body.password, user.hashed_password):
        if user and user.google_sub:
            raise HTTPException(
                status_code=401,
                detail="Nieprawidłowe hasło. To konto możesz też zalogować przez Google lub ustawić hasło (reset hasła).",
            )
        raise HTTPException(status_code=401, detail="Nieprawidłowy e-mail lub hasło")

    user.last_seen_at = datetime.utcnow()
    db.commit()
    token = create_access_token(user.id)
    return TokenResponse(
        access_token=token,
        user=UserResponse.from_user(user),
    )


@app.post("/api/auth/forgot-password", response_model=MessageResponse)
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    try:
        request_password_reset(db, body.email)
    except Exception as exc:
        logging.getLogger("password_reset").error("Reset email failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Nie udało się wysłać wiadomości. Spróbuj ponownie za chwilę.",
        ) from exc
    return MessageResponse(
        message=(
            "Jeśli konto z tym adresem e-mail istnieje, wysłaliśmy link do resetu hasła. "
            "Sprawdź skrzynkę (także spam)."
        )
    )


@app.post("/api/auth/reset-password", response_model=MessageResponse)
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    try:
        reset_password_with_code(db, body.code, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(message="Hasło zostało zmienione. Możesz się zalogować.")


@app.get("/api/auth/me", response_model=UserResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    touch_user_last_seen(user.id)
    return UserResponse.from_user(user, is_site_owner=is_site_owner(user))


@app.get("/api/favorites", response_model=List[FavoriteGameResponse])
def list_favorites(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )
    game_ids = [fav.game_id for fav in rows]
    games = {g.id: g for g in db.query(Game).filter(Game.id.in_(game_ids)).all()} if game_ids else {}
    best_map = _best_offers_map(db, game_ids)
    steam_map = _steam_offers_map(db, game_ids)
    out: list[FavoriteGameResponse] = []
    for fav in rows:
        game = games.get(fav.game_id)
        if not game:
            continue
        item = _game_list_item(game, best_map.get(game.id), steam_map.get(game.id))
        out.append(
            FavoriteGameResponse(
                **item.model_dump(),
                favorited_at=fav.created_at,
                alert_enabled=bool(fav.alert_enabled),
                target_price_pln=fav.target_price_pln,
                baseline_price_pln=fav.baseline_price_pln,
                alert_shop_filter=getattr(fav, "alert_shop_filter", None) or "any",
            )
        )
    return out


@app.post("/api/favorites/{game_id}")
def add_favorite(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        raise HTTPException(status_code=404, detail="Gra nie znaleziona")

    existing = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.game_id == game_id)
        .first()
    )
    if existing:
        return {"ok": True, "message": "Już na liście ulubionych"}

    db.add(Favorite(user_id=user.id, game_id=game_id))
    db.commit()
    set_favorite_alert(db, user_id=user.id, game_id=game_id, enabled=True)
    return {"ok": True, "message": "Dodano do ulubionych"}


@app.delete("/api/favorites/{game_id}")
def remove_favorite(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.game_id == game_id)
        .first()
    )
    if not fav:
        raise HTTPException(status_code=404, detail="Brak na liście ulubionych")
    db.delete(fav)
    db.commit()
    return {"ok": True, "message": "Usunięto z ulubionych"}


@app.get("/api/favorites/check/{game_id}")
def check_favorite(
    game_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.game_id == game_id)
        .first()
    )
    if not fav:
        return {"favorited": False, "alert_enabled": False, "alert_shop_filter": "any"}
    return {
        "favorited": True,
        "game_id": game_id,
        "alert_enabled": bool(fav.alert_enabled),
        "target_price_pln": fav.target_price_pln,
        "alert_shop_filter": getattr(fav, "alert_shop_filter", None) or "any",
    }


@app.get("/api/favorites/check/slug/{slug}")
def check_favorite_by_slug(
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = _find_game_by_slug(db, slug)
    if not game:
        return {"favorited": False, "alert_enabled": False}
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.game_id == game.id)
        .first()
    )
    if not fav:
        return {"favorited": False, "game_id": game.id, "alert_enabled": False, "alert_shop_filter": "any"}
    return {
        "favorited": True,
        "game_id": game.id,
        "alert_enabled": bool(fav.alert_enabled),
        "target_price_pln": fav.target_price_pln,
        "alert_shop_filter": getattr(fav, "alert_shop_filter", None) or "any",
    }


@app.post("/api/favorites/slug/{slug}")
def add_favorite_by_slug(
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = _find_game_by_slug(db, slug, create_stub=True)
    if not game:
        raise HTTPException(status_code=404, detail="Gra nie znaleziona")
    existing = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.game_id == game.id)
        .first()
    )
    if existing:
        return {"ok": True, "game_id": game.id, "message": "Już śledzisz tę grę"}
    db.add(Favorite(user_id=user.id, game_id=game.id))
    db.commit()
    set_favorite_alert(db, user_id=user.id, game_id=game.id, enabled=True)
    return {"ok": True, "game_id": game.id}


@app.delete("/api/favorites/slug/{slug}")
def remove_favorite_by_slug(
    slug: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = _find_game_by_slug(db, slug)
    if not game:
        raise HTTPException(status_code=404, detail="Gra nie znaleziona")
    (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id, Favorite.game_id == game.id)
        .delete()
    )
    db.commit()
    return {"ok": True}


@app.patch("/api/favorites/slug/{slug}/alert")
def update_favorite_alert_by_slug(
    slug: str,
    body: FavoriteAlertUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    game = _find_game_by_slug(db, slug, create_stub=True)
    if not game:
        raise HTTPException(status_code=404, detail="Gra nie znaleziona")
    fav = set_favorite_alert(
        db,
        user_id=user.id,
        game_id=game.id,
        enabled=body.alert_enabled,
        target_price_pln=body.target_price_pln,
        alert_shop_filter=body.alert_shop_filter,
    )
    return {
        "ok": True,
        "game_id": game.id,
        "alert_enabled": fav.alert_enabled,
        "target_price_pln": fav.target_price_pln,
        "alert_shop_filter": getattr(fav, "alert_shop_filter", None) or "any",
    }


@app.get("/api/account/telegram-link", response_model=TelegramLinkResponse)
def get_telegram_link(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    token = ensure_telegram_link_token(db, user)
    bot_user = os.getenv("TELEGRAM_BOT_USERNAME", "kupujpl_bot").strip()
    return TelegramLinkResponse(
        bot_username=bot_user,
        link_token=token,
        start_command=f"/start {token}",
    )


@app.patch("/api/account/alerts")
def update_account_alerts(
    body: AccountAlertsUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user.email_alerts_enabled = body.email_alerts_enabled
    db.commit()
    return {"ok": True, "email_alerts_enabled": user.email_alerts_enabled}


@app.get("/api/push/vapid-public-key", response_model=VapidPublicKeyResponse)
def push_vapid_public_key():
    key = get_vapid_public_key()
    return VapidPublicKeyResponse(configured=vapid_configured(), public_key=key)


@app.get("/api/push/status", response_model=PushStatusResponse)
def push_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return PushStatusResponse(**user_push_status(db, user.id))


@app.post("/api/push/subscribe")
def push_subscribe(
    body: PushSubscriptionIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not vapid_configured():
        raise HTTPException(status_code=503, detail="Powiadomienia push nie są skonfigurowane na serwerze.")
    endpoint = (body.endpoint or "").strip()
    if not endpoint:
        raise HTTPException(status_code=400, detail="Brak endpointu subskrypcji.")
    upsert_push_subscription(
        db,
        user_id=user.id,
        endpoint=endpoint,
        p256dh=body.keys.p256dh,
        auth_key=body.keys.auth,
        user_agent=(request.headers.get("user-agent") or "")[:240],
    )
    return {"ok": True, "message": "Powiadomienia push włączone."}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(
    body: PushUnsubscribeIn | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    endpoint = body.endpoint if body else None
    removed = remove_push_subscription(db, user_id=user.id, endpoint=endpoint)
    return {"ok": True, "removed": removed}


@app.post("/api/telegram/webhook")
async def telegram_webhook(request: Request, db: Session = Depends(get_db)):
    if not bot_configured():
        raise HTTPException(status_code=503, detail="Bot not configured")
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        raise HTTPException(status_code=403, detail="Forbidden")
    update = await request.json()
    handle_telegram_update(db, update)
    return {"ok": True}


@app.post("/api/admin/process-alerts")
def admin_process_alerts(
    db: Session = Depends(get_db),
    _admin=Depends(require_panel3_admin),
):
    return process_price_alerts(db)


@app.post("/api/admin/post-deals")
def admin_post_deals(
    force: bool = Query(True, description="Wymuś post niezależnie od limitu dziennego"),
    db: Session = Depends(get_db),
    _admin=Depends(require_panel3_admin),
):
    from app.core.deals_channel import post_daily_deals

    return post_daily_deals(db, force=force)


@app.get("/api/account/summary", response_model=AccountSummaryResponse)
def account_summary(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    touch_user_last_seen(user.id)
    db.refresh(user)
    return AccountSummaryResponse(**get_account_summary(db, user))


@app.post("/api/account/change-password", response_model=MessageResponse)
def account_change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        change_user_password(
            db,
            user,
            current=body.current_password,
            new_password=body.new_password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MessageResponse(message="Hasło zostało zmienione.")


@app.post("/api/favorites/refresh-offers", response_model=MessageResponse)
def refresh_favorite_offers(
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(8, ge=1, le=16),
):
    game_ids = [
        fav.game_id
        for fav in (
            db.query(Favorite)
            .filter(Favorite.user_id == user.id)
            .order_by(Favorite.created_at.desc())
            .limit(limit)
            .all()
        )
    ]
    if not game_ids:
        return MessageResponse(message="Brak śledzonych gier do odświeżenia.")

    for gid in game_ids:
        background_tasks.add_task(refresh_offers_for_game, gid, fill_missing=True)

    n = len(game_ids)
    word = "grę" if n == 1 else "gry" if n < 5 else "gier"
    return MessageResponse(message=f"Odświeżanie cen dla {n} {word} w tle…")


@app.get("/api/panel/home-curation", response_model=HomeCurationResponse)
def get_home_curation(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_site_owner(user)
    return _curation_response(db)


@app.put("/api/panel/home-curation", response_model=HomeCurationResponse)
def update_home_curation(
    body: HomeCurationUpdateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_site_owner(user)
    if len(body.spotlight_slugs) > MAX_SPOTLIGHT:
        raise HTTPException(
            status_code=400,
            detail=f"Maksymalnie {MAX_SPOTLIGHT} gier w spotlight",
        )
    save_curation(body.spotlight_slugs)
    return _curation_response(db)


@app.post("/api/panel/home-curation/import-steam", response_model=HomeCurationGameResponse)
def import_steam_for_curation(
    body: HomeCurationImportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_site_owner(user)
    try:
        game = import_game_from_steam(db, body.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    best_map = _best_offers_map(db, [game.id])
    steam_map = _steam_offers_map(db, [game.id])
    base = _game_list_item(game, best_map.get(game.id), steam_map.get(game.id))
    return HomeCurationGameResponse(
        **base.model_dump(),
        in_stock_shop_count=_in_stock_shop_count(game),
    )


@app.post("/api/panel/home-curation/{slug}/scan-all", response_model=RefreshOffersResponse)
def scan_all_shops_for_spotlight_game(
    slug: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_site_owner(user)
    game = _find_game_by_slug(db, slug)
    if not game:
        raise HTTPException(status_code=404, detail="Gra nie znaleziona")
    game = _load_game_with_offers(db, game.id)
    updated_at = _offers_updated_at(game)
    _queue_offer_refresh(background_tasks, game, force=True)
    return RefreshOffersResponse(
        queued=True,
        offers_updated_at=updated_at,
        message="Skan wszystkich sklepów uruchomiony w tle…",
    )


@app.post("/api/favorites/import-steam-wishlist", response_model=SteamWishlistImportResponse)
def import_steam_wishlist_endpoint(
    body: SteamWishlistImportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.core.steam_wishlist_import import import_steam_wishlist, wishlist_error_to_http
    from app.parsers.steam_wishlist import SteamWishlistError

    touch_user_last_seen(user.id)
    try:
        result = import_steam_wishlist(db, user_id=user.id, profile_input=body.profile)
        return SteamWishlistImportResponse(**result)
    except SteamWishlistError as exc:
        status, payload = wishlist_error_to_http(exc)
        raise HTTPException(status_code=status, detail=payload) from exc


@app.get("/api/categories", response_model=List[CategoryResponse])
def list_categories(
    kind: Optional[str] = Query(None, description="genre | feature"),
    db: Session = Depends(get_db),
):
    from app.parsers.steam_lists import GENRE_SLUG_TO_TAG

    q = db.query(Category).order_by(Category.game_count.desc(), Category.name)
    if kind in ("genre", "feature"):
        q = q.filter(Category.kind == kind)
    rows = q.all()
    if kind == "genre":
        allowed = set(GENRE_SLUG_TO_TAG.keys())
        rows = [
            c
            for c in rows
            if c.slug in allowed
            and not is_hidden_public_category_slug(c.slug)
            and (c.game_count or 0) > 0
        ]
    return rows


@app.get("/api/catalog/status")
def catalog_status(db: Session = Depends(get_db)):
    total_in_db = db.query(Game).count()
    visible = get_visible_games_count(db)
    enriched = db.query(Game).filter(Game.steam_enriched == True).count()
    categories = db.query(Category).count()
    offer_rows = (
        db.query(Offer.shop_name, func.count(Offer.id))
        .group_by(Offer.shop_name)
        .all()
    )
    return {
        **get_catalog_progress(),
        "games_total": visible,
        "games_in_db": total_in_db,
        "games_enriched": enriched,
        "categories_total": categories,
        "offers_by_shop": {name: count for name, count in offer_rows},
        "offer_scheduler": get_scheduler_status(),
    }


@app.post("/api/parser/refresh-offers")
def trigger_offer_refresh_cycle(request: Request, background_tasks: BackgroundTasks):
    """Manual trigger: refresh stale offers batch (same as background scheduler)."""
    require_panel3_admin(request)

    def _job():
        try:
            run_offer_refresh_cycle(force=True)
        except Exception as exc:
            logging.getLogger("offer_scheduler").error("Manual offer refresh failed: %s", exc)

    background_tasks.add_task(_job)
    return {"message": "Odświeżanie cen sklepów uruchomione w tle."}


@app.post("/api/parser/steam-catalog")
def trigger_steam_catalog(
    request: Request,
    background_tasks: BackgroundTasks,
    source: str = Query("auto", description="auto | istore | steamspy | search | both"),
    max_pages: int = Query(250, ge=10, le=400),
    enrich_limit: int = Query(8000, ge=100, le=50000),
    force_applist_refresh: bool = Query(False),
):
    require_panel3_admin(request)

    if source not in ("auto", "istore", "steamspy", "search", "both"):
        raise HTTPException(
            status_code=400,
            detail="source must be auto, istore, steamspy, search, or both",
        )

    def _job():
        db = SessionLocal()
        try:
            run_steam_catalog_import(
                db,
                source=source,  # type: ignore[arg-type]
                max_pages=max_pages,
                enrich_limit=enrich_limit,
                force_applist_refresh=force_applist_refresh,
            )
        finally:
            db.close()

    background_tasks.add_task(_job)
    return {
        "message": "Import katalogu Steam uruchomiony w tle.",
        "source": source,
        "max_pages": max_pages,
        "enrich_limit": enrich_limit,
    }


def _game_list_from_cache_item(item: dict[str, Any]) -> GameListResponse:
    appid = item.get("appid")
    title = item.get("title") or f"Gra {appid}"
    return GameListResponse(
        id=item.get("game_id") or 0,
        title=title,
        slug=item.get("slug") or f"{slugify(title)}-{appid}",
        cover_image=list_cover_image(item.get("cover_image"), appid),
        steam_appid=appid,
        release_date=item.get("release_date"),
        rating=item.get("rating"),
        best_price_pln=item.get("best_price_pln"),
        best_price_is_official=item.get("best_price_is_official"),
        best_shop_name=item.get("best_shop_name"),
        steam_price_pln=item.get("steam_price_pln"),
        savings_pln=item.get("savings_pln"),
        savings_pct=item.get("savings_pct"),
        offers_updated_at=item.get("offers_updated_at"),
    )


def _game_list_from_steam_item(
    game: Game | None,
    item: dict[str, Any],
    best: Offer | None,
    steam: Offer | None = None,
) -> GameListResponse:
    appid = item.get("appid")
    title = item.get("title") or (game.title if game else None) or f"Gra {appid}"
    if game and game.steam_enriched:
        title = game.title
    cover_src = item.get("cover_image")
    if game and game.steam_enriched and game.cover_image:
        cover_src = game.cover_image
    slug = game.slug if game else f"{slugify(title)}-{appid}"
    savings = _savings_vs_steam(best, steam)
    best_price = best.price_pln if best else None
    label = lowest_ever_label_pl(game, best_price) if game else None
    return GameListResponse(
        id=game.id if game else 0,
        title=title,
        slug=slug,
        cover_image=list_cover_image(cover_src, appid),
        steam_appid=appid,
        release_date=game.release_date if game else None,
        rating=game.rating if game else None,
        best_price_pln=best_price,
        best_price_is_official=best.is_official if best else None,
        best_shop_name=best.shop_name if best else None,
        steam_price_pln=savings["steam_price_pln"],
        savings_pln=savings["savings_pln"],
        savings_pct=savings["savings_pct"],
        lowest_ever_pln=game.lowest_ever_pln if game else None,
        avg_best_price_30d=game.avg_best_price_30d if game else None,
        lowest_ever_label=label,
        at_historical_low=bool(label),
        is_free=bool(game.is_free) if game else False,
    )


@app.get("/api/home", response_model=HomePageResponse)
def get_home_page(
    db: Session = Depends(get_db),
    region: str = Query("pl", description="Shopping region: pl|us"),
):
    region = _normalize_shopping_region(region)
    steam_shop = _steam_shop_for_region(region)
    steam_fallback = "Steam" if region == "us" else None
    curation = load_curation()
    spotlight = _spotlight_game_responses(db, curation.get("spotlight_slugs") or [])
    cache = _load_cache()

    def _pack_games(games: list[Game], ages: dict[int, str] | None = None) -> list[GameListResponse]:
        if not games:
            return []
        ids = [g.id for g in games]
        best_map = _best_offers_map(db, ids, region=region)
        steam_map = _steam_offers_map(
            db, ids, shop_name=steam_shop, fallback_shop=steam_fallback
        )
        out: list[GameListResponse] = []
        for g in games:
            out.append(
                _game_list_item(
                    g,
                    best_map.get(g.id),
                    steam_map.get(g.id),
                    deal_age_label=(ages or {}).get(g.id),
                )
            )
        return out

    try:
        hist_games = games_at_historical_low(db, limit=14)
        historical_lows = _pack_games(hist_games)
    except Exception:
        historical_lows = []

    try:
        new_rows = games_new_deals(db, limit=14, hours=48)
        ages = {g.id: deal_age_label(ts) or "" for g, ts in new_rows}
        new_deals = _pack_games([g for g, _ in new_rows], ages)
    except Exception:
        new_deals = []

    try:
        freebies = _pack_games(games_freebies(db, limit=12))
    except Exception:
        freebies = []

    if not cache:
        return HomePageResponse(
            sections=[],
            spotlight=spotlight,
            new_deals=new_deals,
            historical_lows=historical_lows,
            freebies=freebies,
            updated_at=None,
        )

    sections: list[HomeSectionResponse] = []
    for section in cache.get("sections") or []:
        items = section.get("games") or []
        if not items:
            continue
        appids = [i["appid"] for i in items if i.get("appid")]
        db_games = {
            g.steam_appid: g
            for g in db.query(Game).filter(Game.steam_appid.in_(appids)).all()
        } if appids else {}
        best_map = _best_offers_map(db, [g.id for g in db_games.values()], region=region)
        steam_map = _steam_offers_map(
            db,
            [g.id for g in db_games.values()],
            shop_name=steam_shop,
            fallback_shop=steam_fallback,
        )
        min_reviews = min_reviews_for_list_slug(section.get("slug"))
        offer_counts = in_stock_offer_counts(db, [g.id for g in db_games.values() if g.id])

        games_out: list[GameListResponse] = []
        seen: set[int] = set()
        for item in items:
            aid = item.get("appid")
            if not aid or aid in seen:
                continue
            seen.add(aid)
            game = db_games.get(aid)
            offers = None
            if game:
                offers = offer_counts.get(game.id, 0)
            if is_hidden_from_catalog(game, min_reviews=min_reviews, in_stock_offers=offers):
                continue
            if game:
                games_out.append(
                    _game_list_from_steam_item(
                        game,
                        item,
                        best_map.get(game.id),
                        steam_map.get(game.id),
                    )
                )

        if games_out:
            sections.append(
                HomeSectionResponse(
                    slug=section["slug"],
                    catalog_slug=section.get("catalog_slug") or section["slug"],
                    name=section["name"],
                    subtitle=section.get("subtitle") or "",
                    games=games_out,
                )
            )
    response = HomePageResponse(
        sections=sections,
        spotlight=spotlight,
        new_deals=new_deals,
        historical_lows=historical_lows,
        freebies=freebies,
        updated_at=cache.get("updated_at"),
    )
    _price_debug_log(
        "Home price response",
        {
            "sections": [
                {
                    "slug": section.slug,
                    "games": [
                        {
                            "slug": game.slug,
                            "title": game.title,
                            "bestShopName": game.best_shop_name,
                            "bestPricePln": game.best_price_pln,
                            "offersUpdatedAt": game.offers_updated_at,
                        }
                        for game in section.games[:8]
                    ],
                }
                for section in response.sections[:4]
            ],
        },
    )
    return response


@app.post("/api/parser/refresh-home")
def trigger_home_refresh(request: Request, background_tasks: BackgroundTasks):
    require_panel3_admin(request)

    def _job():
        db = SessionLocal()
        try:
            refresh_home_cache(db)
        finally:
            db.close()

    background_tasks.add_task(_job)
    return {"message": "Odświeżanie strony głównej w tle."}


@app.post("/api/parser/prefetch-featured")
def trigger_featured_prefetch(
    request: Request,
    background_tasks: BackgroundTasks,
    force: bool = Query(False),
):
    require_panel3_admin(request)
    background_tasks.add_task(run_featured_offer_prefetch, force=force)
    return {"message": "Prefetch ofert dla polecanych gier uruchomiony w tle."}


_GAMES_SORTS = {"relevance", "price_asc", "price_desc", "rating", "release", "title"}
_GAMES_CACHE: dict[str, tuple[float, str, GamesPageResponse]] = {}
_GAMES_CACHE_LOCK = threading.Lock()
_GAMES_CACHE_TTL = float(os.environ.get("GAMES_CACHE_TTL", "90"))
_GAMES_CACHE_MAX = 256


def _games_cache_key(q, category, sort, page, limit, region: str = "pl") -> str:
    raw = (
        f"{(q or '').strip().lower()}|{(category or '').strip().lower()}|"
        f"{sort}|{page}|{limit}|{_normalize_shopping_region(region)}"
    )
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _games_cache_get(key: str) -> tuple[str, GamesPageResponse] | None:
    now = time.time()
    with _GAMES_CACHE_LOCK:
        entry = _GAMES_CACHE.get(key)
        if not entry:
            return None
        expires_at, etag, payload = entry
        if expires_at < now:
            _GAMES_CACHE.pop(key, None)
            return None
        return etag, payload


def _games_cache_set(key: str, etag: str, payload: GamesPageResponse) -> None:
    with _GAMES_CACHE_LOCK:
        if len(_GAMES_CACHE) >= _GAMES_CACHE_MAX:
            # Drop the soonest-to-expire entry to bound memory.
            oldest = min(_GAMES_CACHE.items(), key=lambda kv: kv[1][0])[0]
            _GAMES_CACHE.pop(oldest, None)
        _GAMES_CACHE[key] = (time.time() + _GAMES_CACHE_TTL, etag, payload)


def _games_response(
    request: Request,
    response: Response,
    payload: GamesPageResponse,
    etag: str,
):
    """Attach cache headers; return 304 when the client's ETag still matches."""
    inm = request.headers.get("if-none-match")
    if inm and etag in inm:
        return Response(
            status_code=304,
            headers={"ETag": etag, "Cache-Control": "public, max-age=60"},
        )
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "public, max-age=60"
    return payload


@app.get("/api/games", response_model=GamesPageResponse)
def get_games(
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None, description="Search games by title"),
    category: Optional[str] = Query(None, description="Category slug"),
    sort: Optional[str] = Query(None, description="Sort: price_asc|price_desc|rating|release|title"),
    page: int = Query(1, ge=1),
    limit: int = Query(48, ge=12, le=96),
    region: str = Query("pl", description="Shopping region: pl|us"),
):
    sort = sort if sort in _GAMES_SORTS else None
    region = _normalize_shopping_region(region)
    steam_shop = _steam_shop_for_region(region)
    steam_fallback = "Steam" if region == "us" else None

    # Serve from the short-TTL cache when possible (skips the expensive COUNT +
    # offer-map queries). The Steam-list branch below is intentionally not
    # cached because it also hydrates stub rows in the background.
    cache_key = _games_cache_key(q, category, sort, page, limit, region)
    cached = _games_cache_get(cache_key)
    if cached is not None:
        return _games_response(request, response, cached[1], cached[0])

    if category and not q:
        cat_slug = (resolve_category_slug(db, category) or category).strip().lower()
        if is_hidden_public_category_slug(cat_slug):
            return GamesPageResponse(items=[], total=0, page=1, pages=1, limit=limit)
        if uses_steam_list(cat_slug) and _list_spec(cat_slug, db):
            page_items, total = fetch_steam_list_slice(
                cat_slug, db, page=page, limit=limit
            )
            appids = sync_steam_list_games(db, page_items)
            try:
                db.commit()
            except Exception:
                db.rollback()

            background_tasks.add_task(hydrate_steam_list_games, appids, limit=24)

            db_games = {
                g.steam_appid: g
                for g in db.query(Game).filter(Game.steam_appid.in_(appids)).all()
            } if appids else {}
            best_map = _best_offers_map(
                db, [g.id for g in db_games.values()], region=region
            )
            steam_map = _steam_offers_map(
                db,
                [g.id for g in db_games.values()],
                shop_name=steam_shop,
                fallback_shop=steam_fallback,
            )

            items_out: list[GameListResponse] = []
            for item in page_items:
                aid = item.get("appid")
                game = db_games.get(aid) if aid else None
                best = best_map.get(game.id) if game else None
                steam = steam_map.get(game.id) if game else None
                items_out.append(_game_list_from_steam_item(game, item, best, steam))

            pages = max(1, math.ceil(total / limit)) if total else 1
            page = min(page, pages)
            payload_a = GamesPageResponse(
                items=items_out,
                total=total,
                page=page,
                pages=pages,
                limit=limit,
            )
            return payload_a

    query = db.query(Game)
    query = exclude_hidden_games_query(query)
    if q:
        query = apply_game_search(query, q)
        query = apply_search_quality_filter(query)

    if category:
        cat_slug = (resolve_category_slug(db, category) or category).strip().lower()
        if is_hidden_public_category_slug(cat_slug):
            return GamesPageResponse(items=[], total=0, page=1, pages=1, limit=limit)
        query = (
            query.join(game_categories)
            .join(Category)
            .filter(Category.slug == cat_slug)
        )

    needs_distinct = bool(category)

    # Sort by a cheap min-price subquery when requested (approximate ordering;
    # exact best price is still resolved per row below via _best_offers_map).
    price_col = None
    if sort in ("price_asc", "price_desc"):
        display_shops = list(_display_shops_for_region(region))
        price_sq = (
            db.query(
                Offer.game_id.label("gid"),
                func.min(Offer.price_pln).label("minp"),
            )
            .filter(
                Offer.in_stock.is_(True),
                Offer.price_pln > 0,
                Offer.shop_name.in_(display_shops),
            )
            .group_by(Offer.game_id)
            .subquery()
        )
        query = query.outerjoin(price_sq, price_sq.c.gid == Game.id)
        price_col = price_sq.c.minp

    total = query.distinct().count() if needs_distinct else query.count()
    pages = max(1, math.ceil(total / limit))
    page = min(page, pages)

    if sort == "price_asc":
        rows_q = query.order_by(price_col.is_(None), price_col.asc(), Game.title.asc())
    elif sort == "price_desc":
        rows_q = query.order_by(price_col.is_(None), price_col.desc(), Game.title.asc())
    elif sort == "rating":
        rows_q = query.order_by(Game.rating.is_(None), Game.rating.desc(), Game.title.asc())
    elif sort == "release":
        rows_q = query.order_by(Game.release_date.is_(None), Game.release_date.desc(), Game.title.asc())
    elif sort == "title":
        rows_q = query.order_by(Game.title.asc())
    else:
        rows_q = search_order(query) if q else query.order_by(Game.title.asc())
    if needs_distinct:
        rows_q = rows_q.distinct()
    rows = rows_q.offset((page - 1) * limit).limit(limit).all()
    best_map = _best_offers_map(db, [g.id for g in rows], region=region)
    steam_map = _steam_offers_map(
        db,
        [g.id for g in rows],
        shop_name=steam_shop,
        fallback_shop=steam_fallback,
    )
    payload = GamesPageResponse(
        items=[_game_list_item(g, best_map.get(g.id), steam_map.get(g.id)) for g in rows],
        total=total,
        page=page,
        pages=pages,
        limit=limit,
    )
    etag = 'W/"' + hashlib.md5(payload.model_dump_json().encode("utf-8")).hexdigest() + '"'
    _games_cache_set(cache_key, etag, payload)
    _price_debug_log(
        "Games price response",
        {
            "source": "catalog",
            "category": category,
            "query": q,
            "page": page,
            "items": [
                {
                    "slug": item.slug,
                    "title": item.title,
                    "bestShopName": item.best_shop_name,
                    "bestPricePln": item.best_price_pln,
                }
                for item in payload.items[:12]
            ],
        },
    )
    return _games_response(request, response, payload, etag)


@app.get("/api/games/{slug}", response_model=GameResponse)
def get_game_by_slug(
    slug: str,
    db: Session = Depends(get_db),
    region: str = Query("pl", description="Shopping region: pl|us"),
):
    region = _normalize_shopping_region(region)
    game = _find_game_by_slug(db, slug, create_stub=True)
    if game:
        game = _load_game_with_offers(db, game.id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    if not game.steam_enriched and game.steam_appid:
        try:
            if enrich_game(db, game):
                db.commit()
                game = _load_game_with_offers(db, game.id)
        except Exception as exc:
            logging.getLogger("games").warning("Sync enrich failed for %s: %s", slug, exc)
            db.rollback()
            game = _load_game_with_offers(db, game.id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")

    if game.steam_appid and not game.steam_app_type:
        from app.parsers.steam_catalog import fetch_appdetails

        data = fetch_appdetails(game.steam_appid)
        if data:
            apply_appdetails_metadata(game, data)
            try:
                db.commit()
                db.refresh(game)
            except Exception:
                db.rollback()

    if game.steam_appid and game.steam_review_count is None:
        summary = fetch_review_summary(game.steam_appid)
        if summary:
            apply_review_summary_to_game(game, summary)
            try:
                db.commit()
                db.refresh(game)
            except Exception:
                db.rollback()

    if region == "us" and game.steam_appid:
        try:
            from app.parsers.steam_catalog import refresh_steam_offer_for_game

            if refresh_steam_offer_for_game(db, game, cc="us", shop_name="Steam US"):
                db.commit()
                game = _load_game_with_offers(db, game.id)
        except Exception as exc:
            logging.getLogger("games").warning(
                "Steam US refresh failed for %s: %s", slug, exc
            )
            db.rollback()
            game = _load_game_with_offers(db, game.id)

    game.offers = _sorted_offers(game, region=region)
    game.cover_image = effective_cover(game.cover_image, game.steam_appid)
    dlc_games = related_dlc_games(db, game, limit=8)
    dlc_ids = [g.id for g in dlc_games]
    parent_row = parent_game_for_dlc(db, game)
    parent_ids = [parent_row.id] if parent_row else []
    map_ids = dlc_ids + parent_ids
    dlc_best = _best_offers_map(db, map_ids, region=region) if map_ids else {}
    dlc_steam = (
        _steam_offers_map(
            db,
            map_ids,
            shop_name=_steam_shop_for_region(region),
            fallback_shop="Steam" if region == "us" else None,
        )
        if map_ids
        else {}
    )
    related = [_game_list_item(g, dlc_best.get(g.id), dlc_steam.get(g.id)) for g in dlc_games]
    parent_resp = None
    if parent_row:
        parent_resp = _game_list_item(
            parent_row, dlc_best.get(parent_row.id), dlc_steam.get(parent_row.id)
        )
    response = _game_to_response(
        game, related_dlc=related, parent_game=parent_resp, region=region
    )
    _price_debug_log(
        "Game detail price response",
        {
            "slug": response.slug,
            "title": response.title,
            "inStockShopCount": response.in_stock_shop_count,
            "offersUpdatedAt": response.offers_updated_at,
            "offers": [
                {
                    "shopName": offer.shop_name,
                    "pricePln": offer.price_pln,
                    "originalPricePln": offer.original_price_pln,
                    "updatedAt": offer.updated_at,
                    "matchConfidence": offer.match_confidence,
                    "lowConfidence": offer.low_confidence,
                }
                for offer in response.offers
            ],
        },
    )
    return response


@app.get("/api/games/{slug}/price-history", response_model=PriceHistoryResponse)
def get_price_history_api(slug: str, db: Session = Depends(get_db)):
    game = _find_game_by_slug(db, slug)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    points = get_price_history(db, game.id, days=90)
    best = _best_offers_map(db, [game.id]).get(game.id)
    best_price = best.price_pln if best else None
    label = lowest_ever_label_pl(game, best_price)
    return PriceHistoryResponse(
        slug=game.slug,
        title=game.title,
        lowest_ever_pln=game.lowest_ever_pln,
        avg_best_price_30d=game.avg_best_price_30d,
        at_historical_low=bool(label),
        points=[PriceHistoryPoint(**p) for p in points],
    )


@app.get("/api/games/{slug}/offers", response_model=List[OfferResponse])
def get_game_offers(
    slug: str,
    db: Session = Depends(get_db),
    region: str = Query("pl", description="Shopping region: pl|us"),
):
    region = _normalize_shopping_region(region)
    game = _find_game_by_slug(db, slug)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    game = _load_game_with_offers(db, game.id)
    response = [_offer_to_response(o) for o in _sorted_offers(game, region=region)]
    _price_debug_log(
        "Game offers price response",
        {
            "slug": slug,
            "offers": [
                {
                    "shopName": offer.shop_name,
                    "pricePln": offer.price_pln,
                    "originalPricePln": offer.original_price_pln,
                    "updatedAt": offer.updated_at,
                    "matchConfidence": offer.match_confidence,
                    "lowConfidence": offer.low_confidence,
                }
                for offer in response
            ],
        },
    )
    return response


@app.post("/api/games/{slug}/refresh-offers", response_model=RefreshOffersResponse)
def trigger_game_offers_refresh(
    slug: str,
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Wymuś pełny skan wszystkich sklepów"),
    admin: bool = Query(False, description="Panel3 override"),
    db: Session = Depends(get_db),
):
    game = _find_game_by_slug(db, slug)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found")
    game = _load_game_with_offers(db, game.id)
    updated_at = _offers_updated_at(game)

    if (
        is_in_tier_a_daily_scan(game)
        and not (force and admin)
        and _in_stock_shop_count(game) >= MIN_SHOPS_TARGET
    ):
        return RefreshOffersResponse(
            queued=False,
            offers_updated_at=updated_at,
            message=(
                "Ta gra jest w codziennym skanie o 02:30. "
                "Ceny odświeżą się automatycznie."
            ),
        )

    if not admin and not force:
        should_queue = _should_queue_offer_refresh(game)
        if should_queue:
            _queue_offer_refresh(background_tasks, game)
            return RefreshOffersResponse(
                queued=True,
                offers_updated_at=updated_at,
                message="Odświeżanie ofert w tle…",
            )
        return RefreshOffersResponse(
            queued=False,
            offers_updated_at=updated_at,
            message=(
                "Oferty są aktualne. "
                f"Ostatnia aktualizacja: {updated_at.strftime('%Y-%m-%d %H:%M') if updated_at else '—'}."
            ),
        )

    should_queue = _should_queue_offer_refresh(game, force=force)
    if should_queue:
        _queue_offer_refresh(background_tasks, game, force=force)
        message = (
            "Odświeżanie ofert w tle."
            if not force
            else "Wymuszony skan ofert w tle."
        )
    else:
        message = "Oferty są aktualne — odświeżanie nie jest potrzebne."
    return RefreshOffersResponse(
        queued=should_queue,
        offers_updated_at=updated_at,
        message=message,
    )


@app.get("/api/parser/audit")
def get_catalog_audit(request: Request, db: Session = Depends(get_db)):
    require_panel3_admin(request)
    return audit_game_catalog(db)


@app.post("/api/parser/enrich-batch")
def trigger_enrich_batch(
    request: Request,
    background_tasks: BackgroundTasks,
    limit: int = Query(40, ge=5, le=500),
):
    require_panel3_admin(request)

    def _job():
        run_enrich_batch(limit=limit)

    background_tasks.add_task(_job)
    return {"message": f"Enrich batch ({limit} gier) uruchomiony w tle."}


@app.post("/api/parser/cleanup-stub-games")
def trigger_stub_cleanup(request: Request, db: Session = Depends(get_db)):
    require_panel3_admin(request)
    return cleanup_mistaken_stub_games(db)


@app.post("/api/parser/backfill-covers")
def trigger_cover_backfill(request: Request, background_tasks: BackgroundTasks):
    require_panel3_admin(request)

    def _job():
        db = SessionLocal()
        try:
            backfill_cover_images(db)
        finally:
            db.close()

    background_tasks.add_task(_job)
    return {"message": "Uzupełnianie okładek uruchomione w tle."}


def run_parsers_task():
    logger = logging.getLogger("background_parsers")
    logger.info("Running background parsers update...")
    db = SessionLocal()
    batch_limit = int(os.environ.get("PARSER_BATCH_LIMIT", "150"))
    try:
        import_steam_games(db)
        import_gog_offers(db, limit=batch_limit)
        import_epic_offers(db, limit=batch_limit)
        import_instant_gaming_offers(db, limit=batch_limit)
        import_eneba_offers(db, limit=batch_limit)
        import_kinguin_offers(db, limit=batch_limit)
        import_cdkeys_offers(db, limit=batch_limit)
        import_gamivo_offers(db, limit=batch_limit)
        import_g2a_offers(db, limit=batch_limit)
    except Exception as e:
        logger.error("Error in background parsers update: %s", e)
    finally:
        db.close()


@app.post("/api/parser/run")
def trigger_parser(request: Request, background_tasks: BackgroundTasks):
    require_panel3_admin(request)
    background_tasks.add_task(run_parsers_task)
    return {"message": "Background parsers triggered successfully."}
