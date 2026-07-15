"""User account helpers for the games panel."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.security import get_password_hash, verify_password
from app.models.models import Favorite, Game, Offer, User


def get_account_summary(db: Session, user: User) -> dict[str, Any]:
    favs = (
        db.query(Favorite)
        .filter(Favorite.user_id == user.id)
        .order_by(Favorite.created_at.desc())
        .all()
    )
    game_ids = [f.game_id for f in favs]
    games = {g.id: g for g in db.query(Game).filter(Game.id.in_(game_ids)).all()} if game_ids else {}

    best_prices: dict[int, float] = {}
    if game_ids:
        rows = (
            db.query(Offer.game_id, Offer.price_pln)
            .filter(Offer.game_id.in_(game_ids), Offer.in_stock == True)
            .order_by(Offer.price_pln.asc())
            .all()
        )
        for gid, price in rows:
            if gid not in best_prices:
                best_prices[gid] = float(price)

    with_price = 0
    cheapest_price: float | None = None
    cheapest_title: str | None = None
    for gid in game_ids:
        price = best_prices.get(gid)
        if price is None:
            continue
        with_price += 1
        if cheapest_price is None or price < cheapest_price:
            cheapest_price = price
            game = games.get(gid)
            cheapest_title = game.title if game else None

    return {
        "email": user.email,
        "member_since": user.created_at,
        "last_seen_at": user.last_seen_at,
        "favorites_count": len(favs),
        "favorites_with_price": with_price,
        "cheapest_price_pln": cheapest_price,
        "cheapest_game_title": cheapest_title,
        "email_alerts_enabled": bool(user.email_alerts_enabled),
    }


def change_user_password(db: Session, user: User, *, current: str, new_password: str) -> None:
    if not user.hashed_password:
        raise ValueError("Ustaw hasło przez „Zapomniałeś hasła?” — konto Google nie ma jeszcze hasła lokalnego.")
    if not verify_password(current, user.hashed_password):
        if user.google_sub:
            raise ValueError(
                "Obecne hasło jest nieprawidłowe. Konto Google może nie mieć hasła — użyj resetu hasła e-mailem."
            )
        raise ValueError("Obecne hasło jest nieprawidłowe")
    user.hashed_password = get_password_hash(new_password)
    db.commit()
