"""Price alert worker: email + Telegram for watched games."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.core.email_service import send_price_alert_email
from app.core.site_config import SITE_ORIGIN
from app.core.telegram_bot import send_telegram_message
from app.models.models import Favorite, Game, Offer, User
from app.parsers.shop_scan_config import get_display_shops

logger = logging.getLogger("price_alerts")

COOLDOWN_HOURS = 24
DROP_EPSILON = 0.05


def _best_offer(db: Session, game_id: int) -> Offer | None:
    active = set(get_display_shops())
    offers = (
        db.query(Offer)
        .filter(
            Offer.game_id == game_id,
            Offer.in_stock.is_(True),
            Offer.shop_name.in_(active),
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
        )
        .order_by(Offer.price_pln.asc())
        .all()
    )
    return offers[0] if offers else None


def _should_notify(fav: Favorite, best_price: float) -> bool:
    if not fav.alert_enabled:
        return False
    baseline = fav.baseline_price_pln
    if baseline is None or best_price >= baseline - DROP_EPSILON:
        return False
    if fav.target_price_pln is not None and best_price > fav.target_price_pln + DROP_EPSILON:
        return False
    if fav.last_notified_at:
        if datetime.utcnow() - fav.last_notified_at < timedelta(hours=COOLDOWN_HOURS):
            return False
    return True


def process_price_alerts(db: Session) -> dict[str, int]:
    """Run after offer scans. Returns counts."""
    rows = (
        db.query(Favorite)
        .filter(Favorite.alert_enabled.is_(True))
        .options(joinedload(Favorite.user), joinedload(Favorite.game))
        .all()
    )
    sent_email = 0
    sent_tg = 0
    sent_push = 0
    checked = 0
    now = datetime.utcnow()

    for fav in rows:
        checked += 1
        user: User = fav.user
        game: Game = fav.game
        if not game:
            continue
        best = _best_offer(db, game.id)
        if not best:
            continue
        best_price = float(best.price_pln)
        if not _should_notify(fav, best_price):
            continue

        drop = (fav.baseline_price_pln or best_price) - best_price
        game_url = f"{SITE_ORIGIN}/gra/{game.slug}?utm_source=alert&utm_medium=email"
        tg_url = f"{SITE_ORIGIN}/gra/{game.slug}?utm_source=alert&utm_medium=telegram"

        if user.email_alerts_enabled:
            try:
                send_price_alert_email(
                    user.email,
                    game_title=game.title,
                    best_price_pln=best_price,
                    shop_name=best.shop_name,
                    baseline_pln=fav.baseline_price_pln,
                    drop_pln=drop,
                    game_url=game_url,
                )
                sent_email += 1
            except Exception as exc:
                logger.warning("Email alert failed for user %s: %s", user.id, exc)

        if user.telegram_chat_id:
            text = (
                f"🔔 Spadek ceny: {game.title}\n"
                f"Teraz: {best_price:.2f} zł ({best.shop_name})\n"
            )
            if fav.baseline_price_pln:
                text += f"Było: {fav.baseline_price_pln:.2f} zł (−{drop:.2f} zł)\n"
            text += f"\n{tg_url}"
            try:
                if send_telegram_message(user.telegram_chat_id, text):
                    sent_tg += 1
            except Exception as exc:
                logger.warning("Telegram alert failed for user %s: %s", user.id, exc)

        push_url = f"{SITE_ORIGIN}/gra/{game.slug}?utm_source=alert&utm_medium=push"
        try:
            from app.core.web_push import send_web_push_to_user

            push_body = f"Teraz {best_price:.2f} zł ({best.shop_name})"
            if fav.baseline_price_pln:
                push_body += f" — było {fav.baseline_price_pln:.2f} zł"
            sent_push += send_web_push_to_user(
                db,
                user_id=user.id,
                title=f"Spadek ceny: {game.title}",
                body=push_body,
                url=push_url,
                tag=f"game-{game.id}",
            )
        except Exception as exc:
            logger.warning("Web push alert failed for user %s: %s", user.id, exc)

        fav.last_notified_at = now
        fav.baseline_price_pln = best_price

    db.commit()
    return {"checked": checked, "email": sent_email, "telegram": sent_tg, "push": sent_push}


def ensure_telegram_link_token(db: Session, user: User) -> str:
    import secrets

    if user.telegram_link_token:
        return user.telegram_link_token
    user.telegram_link_token = secrets.token_urlsafe(24)
    db.commit()
    db.refresh(user)
    return user.telegram_link_token


def set_favorite_alert(
    db: Session,
    *,
    user_id: int,
    game_id: int,
    enabled: bool,
    target_price_pln: float | None = None,
) -> Favorite:
    fav = (
        db.query(Favorite)
        .filter(Favorite.user_id == user_id, Favorite.game_id == game_id)
        .first()
    )
    if not fav:
        fav = Favorite(user_id=user_id, game_id=game_id)
        db.add(fav)
        db.flush()

    best = _best_offer(db, game_id)
    if enabled:
        fav.alert_enabled = True
        fav.target_price_pln = target_price_pln
        if fav.baseline_price_pln is None and best:
            fav.baseline_price_pln = float(best.price_pln)
    else:
        fav.alert_enabled = False
        fav.target_price_pln = None

    db.commit()
    db.refresh(fav)
    return fav
