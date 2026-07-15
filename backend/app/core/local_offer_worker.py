"""Queue + bulk upsert for local PC offer worker."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.database import BASE_DIR
from app.models.models import Game
from app.parsers.game_offers import EXPECTED_SHOPS, _missing_shops, _present_shops, _shop_count
from app.parsers.keyshop_common import upsert_keyshop_offer
from app.parsers.offer_scheduler import select_games_for_refresh

_WORKER_STATE = Path(BASE_DIR) / "tmp" / "local_worker_state.json"


def _save_worker_state(patch: dict[str, Any]) -> None:
    _WORKER_STATE.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if _WORKER_STATE.is_file():
        try:
            state = json.loads(_WORKER_STATE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            state = {}
    state.update(patch)
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _WORKER_STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def build_offer_queue(db: Session, *, limit: int = 40) -> list[dict[str, Any]]:
    games = select_games_for_refresh(db, limit=limit)
    out: list[dict[str, Any]] = []
    for game in games:
        present = sorted(_present_shops(game))
        missing = sorted(_missing_shops(game))
        out.append(
            {
                "game_id": game.id,
                "title": game.title,
                "slug": game.slug,
                "steam_appid": game.steam_appid,
                "shop_count": _shop_count(game),
                "present_shops": present,
                "missing_shops": missing,
            }
        )
    return out


def apply_bulk_offers(
    db: Session,
    updates: list[dict[str, Any]],
    *,
    source: str = "local",
) -> dict[str, Any]:
    games_touched = 0
    offers_upserted = 0
    errors: list[str] = []

    for item in updates:
        game_id = item.get("game_id")
        offers = item.get("offers") or []
        if not game_id or not offers:
            continue
        game = db.query(Game).filter(Game.id == game_id).first()
        if not game:
            errors.append(f"game {game_id} not found")
            continue
        touched = False
        for offer in offers:
            shop = offer.get("shop_name")
            price = offer.get("price_pln")
            url = offer.get("product_url") or offer.get("affiliate_url")
            if not shop or price is None or not url:
                continue
            if shop not in EXPECTED_SHOPS:
                continue
            try:
                upsert_keyshop_offer(
                    db,
                    game,
                    shop,
                    url,
                    float(price),
                    is_official=bool(offer.get("is_official")),
                    match_confidence=offer.get("match_confidence"),
                )
                offers_upserted += 1
                touched = True
            except Exception as exc:
                errors.append(f"{game_id}/{shop}: {exc}")
        if touched:
            games_touched += 1

    db.commit()
    stats = {
        "games_touched": games_touched,
        "offers_upserted": offers_upserted,
        "errors": errors[:20],
        "source": source,
        "received_batches": len(updates),
    }
    _save_worker_state(stats)
    return stats
