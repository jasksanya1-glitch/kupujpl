"""Daily auto-posting of the best game deals to a public Telegram channel.

Drives traffic back to the site: each deal links to the on-site game page
(with UTM tags), not straight to the shop, so readers land on kupujpl.pl/games.
"""
from __future__ import annotations

import html as html_lib
import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import BASE_DIR, SessionLocal
from app.core.game_catalog_filter import exclude_hidden_games_query
from app.core.site_config import SITE_ORIGIN, TELEGRAM_CHANNEL_URL
from app.core.telegram_bot import bot_configured, send_telegram_message
from app.models.models import Game, Offer

logger = logging.getLogger("deals_channel")

_STATE_PATH = BASE_DIR / "tmp" / "deals_channel_state.json"
_LOCK = threading.Lock()
_STARTED = False

CHECK_INTERVAL_SEC = int(os.environ.get("DEALS_CHANNEL_CHECK_INTERVAL", "300"))
# Server runs in UTC; 9 UTC ≈ 11:00 in Warsaw (summer). Configurable.
TARGET_HOUR_UTC = int(os.environ.get("DEALS_CHANNEL_HOUR", "9"))
DEALS_COUNT = int(os.environ.get("DEALS_CHANNEL_COUNT", "8"))
MIN_SAVINGS_PCT = int(os.environ.get("DEALS_CHANNEL_MIN_SAVINGS", "15"))
# Quality gates so we feature recognizable games, not obscure $1 indie keys.
MIN_REVIEWS = int(os.environ.get("DEALS_CHANNEL_MIN_REVIEWS", "300"))
MIN_STEAM_PRICE = float(os.environ.get("DEALS_CHANNEL_MIN_STEAM_PRICE", "25"))


def _load_state() -> dict[str, Any]:
    if not _STATE_PATH.is_file():
        return {}
    try:
        return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict[str, Any]) -> None:
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def channel_chat_id() -> str:
    """Resolve the target channel: explicit chat id, or @username from the URL."""
    explicit = os.environ.get("TELEGRAM_CHANNEL_CHAT_ID", "").strip()
    if explicit:
        return explicit
    match = re.search(r"t\.me/([A-Za-z0-9_]+)", TELEGRAM_CHANNEL_URL or "")
    return f"@{match.group(1)}" if match else ""


def build_top_deals(
    db: Session,
    *,
    limit: int = DEALS_COUNT,
    min_savings_pct: int = MIN_SAVINGS_PCT,
) -> list[tuple[Any, Offer]]:
    """Return [(GameListResponse, best Offer), ...] sorted by biggest savings."""
    # Lazy import to avoid a circular import at module load (main imports this).
    from app.main import _best_offers_map, _game_list_item, _steam_offers_map

    # Prioritise popular, non-free games with real Steam presence. Resolve the
    # candidate ids in a plain Game+Offer join first (no hidden-games subquery,
    # which would auto-correlate and break), then re-select with the catalog
    # visibility filter applied cleanly.
    pop_ids = [
        row[0]
        for row in db.query(Game.id)
        .join(Offer, Offer.game_id == Game.id)
        .filter(
            Offer.in_stock.is_(True),
            Offer.price_pln > 0,
            Game.is_free.is_(False),
            Game.steam_review_count.isnot(None),
            Game.steam_review_count >= MIN_REVIEWS,
        )
        .order_by(Game.steam_review_count.desc())
        .distinct()
        .limit(400)
        .all()
    ]
    if not pop_ids:
        return []
    games = (
        exclude_hidden_games_query(db.query(Game))
        .filter(Game.id.in_(pop_ids))
        .all()
    )
    if not games:
        return []
    gids = [g.id for g in games]
    best_map = _best_offers_map(db, gids)
    steam_map = _steam_offers_map(db, gids)

    deals: list[tuple[Any, Offer]] = []
    for game in games:
        best = best_map.get(game.id)
        if not best:
            continue
        item = _game_list_item(game, best, steam_map.get(game.id))
        if (item.savings_pct or 0) < min_savings_pct:
            continue
        if (item.steam_price_pln or 0) < MIN_STEAM_PRICE:
            continue
        deals.append((item, best))

    deals.sort(
        key=lambda t: (t[0].savings_pct or 0, -(t[0].best_price_pln or 9999)),
        reverse=True,
    )
    return deals[:limit]


def format_deals_post(deals: list[tuple[Any, Offer]]) -> str:
    today = date.today().strftime("%d.%m.%Y")
    lines = [f"🔥 <b>Najlepsze okazje na gry — {today}</b>", ""]
    for i, (item, best) in enumerate(deals, start=1):
        title = html_lib.escape(item.title)
        url = f"{SITE_ORIGIN}/gra/{item.slug}?utm_source=telegram&utm_medium=channel&utm_campaign=daily_deals"
        shop = html_lib.escape(best.shop_name or "")
        price = f"{item.best_price_pln:.2f} zł" if item.best_price_pln else "—"
        line = f'{i}. <a href="{html_lib.escape(url)}"><b>{title}</b></a>\n💰 {price} ({shop})'
        if item.savings_pct and item.steam_price_pln:
            line += f" · <b>−{item.savings_pct}%</b> vs Steam ({item.steam_price_pln:.2f} zł)"
        lines.append(line)
        lines.append("")
    lines.append(
        f'➡️ Więcej okazji: <a href="{SITE_ORIGIN}/promocje?utm_source=telegram&utm_medium=channel">kupujpl.pl/games</a>'
    )
    return "\n".join(lines)


def post_daily_deals(
    db: Session,
    *,
    force: bool = False,
    limit: int = DEALS_COUNT,
    min_savings_pct: int = MIN_SAVINGS_PCT,
) -> dict[str, Any]:
    chat_id = channel_chat_id()
    if not bot_configured() or not chat_id:
        return {"posted": False, "reason": "not_configured", "chat_id": chat_id}

    today_iso = date.today().isoformat()
    if not force:
        with _LOCK:
            if _load_state().get("last_posted_date") == today_iso:
                return {"posted": False, "reason": "already_posted_today"}

    deals = build_top_deals(db, limit=limit, min_savings_pct=min_savings_pct)
    if not deals:
        return {"posted": False, "reason": "no_deals"}

    text = format_deals_post(deals)
    ok = send_telegram_message(
        chat_id, text, parse_mode="HTML", disable_web_page_preview=True
    )
    if ok:
        with _LOCK:
            state = _load_state()
            state["last_posted_date"] = today_iso
            state["last_posted_at"] = datetime.utcnow().isoformat()
            state["last_count"] = len(deals)
            _save_state(state)
        logger.info("Posted %s deals to Telegram channel %s", len(deals), chat_id)
    return {"posted": ok, "count": len(deals), "chat_id": chat_id}


def _loop() -> None:
    logger.info(
        "Deals-channel scheduler started (target %sh UTC, every %ss)",
        TARGET_HOUR_UTC,
        CHECK_INTERVAL_SEC,
    )
    while True:
        try:
            now = datetime.utcnow()
            today_iso = date.today().isoformat()
            if now.hour >= TARGET_HOUR_UTC and _load_state().get("last_posted_date") != today_iso:
                db = SessionLocal()
                try:
                    result = post_daily_deals(db)
                    if result.get("posted"):
                        logger.info("Daily deals posted: %s", result)
                    elif result.get("reason") not in ("already_posted_today",):
                        logger.info("Daily deals not posted: %s", result)
                finally:
                    db.close()
        except Exception as exc:
            logger.error("Deals-channel loop failed: %s", exc)
        time.sleep(CHECK_INTERVAL_SEC)


def start_deals_channel_scheduler() -> None:
    global _STARTED
    if os.environ.get("DEALS_CHANNEL_ENABLED", "1").lower() in ("0", "false", "no"):
        logger.info("Deals-channel scheduler disabled via DEALS_CHANNEL_ENABLED")
        return
    if _STARTED:
        return
    _STARTED = True
    threading.Thread(target=_loop, name="deals-channel", daemon=True).start()
