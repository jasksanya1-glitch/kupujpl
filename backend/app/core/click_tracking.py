"""Outbound affiliate click logging for panel3 analytics."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.affiliate import _is_awin_tracking_url, affiliate_link_configured
from app.models.models import AffiliateClick, Game, Offer

_log = logging.getLogger("click_tracking")

RETENTION_DAYS = 90
NO_COMMISSION_SHOPS = frozenset({"Steam", "Epic Games"})


def _visitor_key(request: Request) -> str:
    ip = (
        request.headers.get("cf-connecting-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or request.headers.get("x-real-ip")
        or (request.client.host if request.client else "")
    )
    ua = request.headers.get("user-agent", "")
    return hashlib.md5(f"{ip}|{ua}".encode()).hexdigest()


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
        visitor_key=_visitor_key(request),
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


def collect_click_stats(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    since_7d = now - timedelta(days=7)
    since_24h = now - timedelta(hours=24)

    total_7d = (
        db.query(func.count(AffiliateClick.id))
        .filter(AffiliateClick.clicked_at >= since_7d)
        .scalar()
        or 0
    )
    tracked_7d = (
        db.query(func.count(AffiliateClick.id))
        .filter(
            AffiliateClick.clicked_at >= since_7d,
            AffiliateClick.has_tracking.is_(True),
        )
        .scalar()
        or 0
    )
    monetized_7d = (
        db.query(func.count(AffiliateClick.id))
        .filter(
            AffiliateClick.clicked_at >= since_7d,
            AffiliateClick.is_monetized.is_(True),
        )
        .scalar()
        or 0
    )
    clicks_24h = (
        db.query(func.count(AffiliateClick.id))
        .filter(AffiliateClick.clicked_at >= since_24h)
        .scalar()
        or 0
    )

    by_shop_rows = (
        db.query(
            AffiliateClick.shop_name,
            func.count(AffiliateClick.id),
            func.max(AffiliateClick.clicked_at),
        )
        .filter(AffiliateClick.clicked_at >= since_7d)
        .group_by(AffiliateClick.shop_name)
        .order_by(func.count(AffiliateClick.id).desc())
        .limit(12)
        .all()
    )
    tracked_by_shop = dict(
        db.query(AffiliateClick.shop_name, func.count(AffiliateClick.id))
        .filter(
            AffiliateClick.clicked_at >= since_7d,
            AffiliateClick.has_tracking.is_(True),
        )
        .group_by(AffiliateClick.shop_name)
        .all()
    )

    recent = (
        db.query(AffiliateClick)
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
