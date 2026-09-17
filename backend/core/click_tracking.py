"""Outbound affiliate click logging for panel3 analytics."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.affiliate import _is_awin_tracking_url, affiliate_link_configured
from app.core.site_tracking import _detect_bot_visit, _visitor_key
from app.models.models import AffiliateClick, Game, Offer, SiteVisit

_log = logging.getLogger("click_tracking")

RETENTION_DAYS = 90
NO_COMMISSION_SHOPS = frozenset({"Steam", "Epic Games"})
_BURST_WINDOW = timedelta(hours=2)
_BURST_LIMIT = 3
_HUMAN_LOOKBACK = timedelta(hours=48)


def _has_tracking(url: str, shop_name: str) -> bool:
    if _is_awin_tracking_url(url):
        return True
    if shop_name in NO_COMMISSION_SHOPS:
        return False
    if "kupujpl" in url and any(
        f"{k}=" in url for k in ("pp=", "ref=", "referral=", "af_id=", "partner=")
    ):
        return False
    return affiliate_link_configured(shop_name) or any(
        token in url
        for token in ("gname=", "glv=", "igr=", "af_id=", "referral=", "ref=", "pp=", "partner=")
    )


def _visitor_has_verified_human(db: Session, visitor_key: str, *, before: datetime) -> bool:
    if not visitor_key:
        return False
    since = before - _HUMAN_LOOKBACK
    base = (
        db.query(SiteVisit.id)
        .filter(
            SiteVisit.visitor_key == visitor_key,
            SiteVisit.visited_at >= since,
            SiteVisit.visited_at <= before,
            SiteVisit.is_suspected_bot.is_(False),
        )
    )
    if base.filter(SiteVisit.is_verified_human.is_(True)).first():
        return True
    return base.filter(SiteVisit.path.like("/gra/%")).first() is not None


def _classify_click_bot(
    db: Session,
    request: Request,
    *,
    visitor_key: str,
    user_agent: str,
    now: datetime,
) -> tuple[bool, str | None]:
    is_bot, reason = _detect_bot_visit(
        request,
        path="/api/go",
        user_agent=user_agent,
        client_agent=None,
    )
    if is_bot and reason not in ("missing_accept_language", "missing_accept"):
        return True, reason or "bot_ua"
    if not _visitor_has_verified_human(db, visitor_key, before=now):
        return True, "no_verified_browse"
    recent = (
        db.query(func.count(AffiliateClick.id))
        .filter(
            AffiliateClick.visitor_key == visitor_key,
            AffiliateClick.clicked_at >= now - _BURST_WINDOW,
        )
        .scalar()
        or 0
    )
    if int(recent) >= _BURST_LIMIT:
        return True, "click_burst"
    return False, None


def log_affiliate_click(
    db: Session,
    *,
    offer: Offer,
    game: Game,
    destination_url: str,
    request: Request,
) -> None:
    host = ""
    try:
        host = urlparse(destination_url).netloc.lower()
    except Exception:
        pass
    shop = offer.shop_name or ""
    now = datetime.utcnow()
    visitor_key = _visitor_key(request)
    user_agent = (request.headers.get("user-agent") or "")[:480]
    is_bot, bot_reason = _classify_click_bot(
        db,
        request,
        visitor_key=visitor_key,
        user_agent=user_agent,
        now=now,
    )
    row = AffiliateClick(
        offer_id=offer.id,
        game_id=game.id,
        game_slug=game.slug,
        game_title=game.title,
        shop_name=shop,
        price_pln=offer.price_pln,
        destination_host=host[:120] if host else None,
        has_tracking=_has_tracking(destination_url, shop),
        is_monetized=shop not in NO_COMMISSION_SHOPS,
        visitor_key=visitor_key,
        user_agent=user_agent or None,
        is_suspected_bot=is_bot,
        bot_reason=bot_reason,
        clicked_at=now,
    )
    db.add(row)
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        _log.warning("click log failed: %s", exc)


def prune_old_clicks(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(days=RETENTION_DAYS)
    deleted = (
        db.query(AffiliateClick)
        .filter(AffiliateClick.clicked_at < cutoff)
        .delete(synchronize_session=False)
    )
    if deleted:
        db.commit()
    return int(deleted)


def backfill_bot_clicks(db: Session, *, hours: int = 72) -> int:
    """Mark historical scraper clicks (no verified browse / burst) as bots."""
    since = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        db.query(AffiliateClick)
        .filter(
            AffiliateClick.clicked_at >= since,
            AffiliateClick.is_suspected_bot.is_(False),
        )
        .all()
    )
    if not rows:
        return 0
    by_key: dict[str, list[AffiliateClick]] = {}
    for row in rows:
        by_key.setdefault(row.visitor_key or "", []).append(row)
    updated = 0
    for vk, clicks in by_key.items():
        clicks.sort(key=lambda c: c.clicked_at or datetime.min)
        has_human = _visitor_has_verified_human(
            db, vk, before=datetime.utcnow()
        ) if vk else False
        for i, click in enumerate(clicks):
            reason = None
            if not has_human:
                reason = "no_verified_browse"
            elif i >= _BURST_LIMIT:
                reason = "click_burst"
            if reason:
                click.is_suspected_bot = True
                click.bot_reason = reason
                updated += 1
    if updated:
        db.commit()
    return updated


def collect_click_stats(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    since_7d = now - timedelta(days=7)
    since_24h = now - timedelta(hours=24)
    human = AffiliateClick.is_suspected_bot.is_(False)

    total_7d = (
        db.query(func.count(AffiliateClick.id))
        .filter(AffiliateClick.clicked_at >= since_7d, human)
        .scalar()
        or 0
    )
    tracked_7d = (
        db.query(func.count(AffiliateClick.id))
        .filter(
            AffiliateClick.clicked_at >= since_7d,
            human,
            AffiliateClick.has_tracking.is_(True),
        )
        .scalar()
        or 0
    )
    monetized_7d = (
        db.query(func.count(AffiliateClick.id))
        .filter(
            AffiliateClick.clicked_at >= since_7d,
            human,
            AffiliateClick.is_monetized.is_(True),
        )
        .scalar()
        or 0
    )
    clicks_24h = (
        db.query(func.count(AffiliateClick.id))
        .filter(AffiliateClick.clicked_at >= since_24h, human)
        .scalar()
        or 0
    )

    by_shop_rows = (
        db.query(
            AffiliateClick.shop_name,
            func.count(AffiliateClick.id),
            func.max(AffiliateClick.clicked_at),
        )
        .filter(AffiliateClick.clicked_at >= since_7d, human)
        .group_by(AffiliateClick.shop_name)
        .order_by(func.count(AffiliateClick.id).desc())
        .limit(12)
        .all()
    )
    tracked_by_shop = dict(
        db.query(AffiliateClick.shop_name, func.count(AffiliateClick.id))
        .filter(
            AffiliateClick.clicked_at >= since_7d,
            human,
            AffiliateClick.has_tracking.is_(True),
        )
        .group_by(AffiliateClick.shop_name)
        .all()
    )

    recent = (
        db.query(AffiliateClick)
        .filter(human)
        .order_by(AffiliateClick.clicked_at.desc())
        .limit(20)
        .all()
    )

    return {
        "clicks_24h": int(clicks_24h),
        "clicks_7d": int(total_7d),
        "tracked_clicks_7d": int(tracked_7d),
        "monetized_clicks_7d": int(monetized_7d),
        "untracked_clicks_7d": int(total_7d - tracked_7d),
        "by_shop": [
            {
                "shop": shop,
                "clicks": int(cnt),
                "tracked": int(tracked_by_shop.get(shop, 0)),
                "last_clicked_at": (last.isoformat() + "Z") if last else None,
            }
            for shop, cnt, last in by_shop_rows
        ],
        "recent": [
            {
                "clicked_at": (r.clicked_at.isoformat() + "Z") if r.clicked_at else None,
                "game_title": r.game_title,
                "game_slug": r.game_slug,
                "shop_name": r.shop_name,
                "price_pln": r.price_pln,
                "has_tracking": r.has_tracking,
                "is_monetized": r.is_monetized,
            }
            for r in recent
        ],
    }
