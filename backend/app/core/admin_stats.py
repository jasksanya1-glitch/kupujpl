"""Aggregate stats for games admin panel3."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.game_audit import audit_game_catalog
from app.core.offer_coverage_stats import collect_offer_coverage_stats
from app.core.site_tracking import collect_traffic_stats
from app.core.affiliate_config import affiliate_env_status
from app.core.click_tracking import collect_click_stats
from app.models.models import Favorite, Game, Offer, User
from app.parsers.offer_scheduler import get_scheduler_status
from app.parsers.tier_a_scan_state import get_tier_a_status
from app.parsers.steam_catalog import get_catalog_progress


def collect_admin_stats(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    since_15m = now - timedelta(minutes=15)
    since_7d = now - timedelta(days=7)

    catalog = audit_game_catalog(db)
    offers_by_shop = dict(
        db.query(Offer.shop_name, func.count(Offer.id))
        .filter(Offer.in_stock == True)
        .group_by(Offer.shop_name)
        .all()
    )

    games_with_offers = (
        db.query(func.count(func.distinct(Offer.game_id)))
        .filter(Offer.in_stock == True)
        .scalar()
        or 0
    )

    users_total = db.query(func.count(User.id)).scalar() or 0
    users_online = (
        db.query(func.count(User.id)).filter(User.last_seen_at >= since_15m).scalar() or 0
    )
    signups_7d = (
        db.query(func.count(User.id)).filter(User.created_at >= since_7d).scalar() or 0
    )
    favorites_total = db.query(func.count(Favorite.id)).scalar() or 0
    users_with_favorites = (
        db.query(func.count(func.distinct(Favorite.user_id))).scalar() or 0
    )

    recent_users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .limit(12)
        .all()
    )
    online_users = (
        db.query(User)
        .filter(User.last_seen_at >= since_15m)
        .order_by(User.last_seen_at.desc())
        .limit(12)
        .all()
    )

    top_watched = (
        db.query(
            Game.id,
            Game.title,
            Game.slug,
            func.count(Favorite.id).label("cnt"),
        )
        .join(Favorite, Favorite.game_id == Game.id)
        .group_by(Game.id)
        .order_by(func.count(Favorite.id).desc())
        .limit(10)
        .all()
    )

    return {
        "generated_at": now.isoformat() + "Z",
        "catalog": {
            **catalog,
            "games_with_offers": int(games_with_offers),
            "offers_by_shop": offers_by_shop,
            "steam_import": get_catalog_progress(),
        },
        "offer_coverage": collect_offer_coverage_stats(db),
        "scheduler": get_scheduler_status(),
        "tier_a": get_tier_a_status(),
        "users": {
            "total": int(users_total),
            "online_15m": int(users_online),
            "signups_7d": int(signups_7d),
            "favorites_total": int(favorites_total),
            "users_with_favorites": int(users_with_favorites),
            "recent": [
                {
                    "id": u.id,
                    "email": u.email,
                    "created_at": (u.created_at.isoformat() + "Z") if u.created_at else None,
                    "last_seen_at": (u.last_seen_at.isoformat() + "Z") if u.last_seen_at else None,
                }
                for u in recent_users
            ],
            "online": [
                {
                    "id": u.id,
                    "email": u.email,
                    "last_seen_at": (u.last_seen_at.isoformat() + "Z") if u.last_seen_at else None,
                }
                for u in online_users
            ],
        },
        "top_watched": [
            {"title": t, "slug": s, "count": int(c)} for _, t, s, c in top_watched
        ],
        "traffic": collect_traffic_stats(db),
        "clicks": collect_click_stats(db),
        "affiliate_config": affiliate_env_status(),
    }
