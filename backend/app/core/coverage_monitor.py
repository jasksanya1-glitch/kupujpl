"""Auth-gated catalog price coverage snapshots (day-over-day compare)."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import BASE_DIR
from app.core.price_engine import best_offers_map_v2
from app.models.models import Game, Offer
from app.parsers.shop_scan_queue import QUEUE_DIR, load_shop_progress

SNAPSHOT_DIR = Path(BASE_DIR) / "tmp" / "coverage_snapshots"
SHOPS = (
    "Steam",
    "GOG",
    "Epic Games",
    "Instant Gaming",
    "Kinguin",
    "G2A",
    "Gamivo",
    "CDKeys",
    "Fanatical",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _day_key(dt: datetime | None = None) -> str:
    return (dt or _utcnow()).strftime("%Y-%m-%d")


def build_coverage_snapshot(db: Session) -> dict[str, Any]:
    """Read-only coverage + scanner effectiveness snapshot."""
    now = _utcnow()
    cut_24 = now - timedelta(hours=24)
    games = db.query(Game).filter(Game.slug.isnot(None)).all()
    ids = [g.id for g in games]
    confirmed_map = best_offers_map_v2(db, ids) if ids else {}

    states = Counter()
    for g in games:
        if bool(getattr(g, "is_free", False)):
            states["free"] += 1
            continue
        if confirmed_map.get(g.id) is not None:
            states["has_confirmed"] += 1
            continue
        offs = list(g.offers or [])
        if not offs:
            states["no_offers"] += 1
            continue
        priced = [
            o
            for o in offs
            if o.in_stock and o.price_pln is not None and float(o.price_pln) > 0
        ]
        if not priced:
            states["offers_oos_or_zero"] += 1
        else:
            # Approximate: without full PE row walk, treat as stale/unconfirmed.
            states["stale_or_unconfirmed"] += 1

    total = len(games)
    confirmed = int(states.get("has_confirmed", 0))
    shop_rows = []
    for shop in SHOPS:
        in_stock = (
            db.query(func.count(Offer.id))
            .filter(Offer.shop_name == shop, Offer.in_stock.is_(True), Offer.price_pln > 0)
            .scalar()
            or 0
        )
        v24 = (
            db.query(func.count(Offer.id))
            .filter(
                Offer.shop_name == shop,
                Offer.last_verified_at.isnot(None),
                Offer.last_verified_at >= cut_24,
            )
            .scalar()
            or 0
        )
        prog = load_shop_progress(shop)
        shop_rows.append(
            {
                "shop": shop,
                "in_stock_priced": in_stock,
                "verified_last_24h": v24,
                "verified_per_hour_est": round(v24 / 24.0, 2),
                "queue_phase": prog.get("phase"),
                "queue_checked": prog.get("checked"),
                "queue_verified": prog.get("verified"),
                "queue_message": (prog.get("message") or "")[:160],
                "last_batch_verified": prog.get("last_batch_verified"),
                "last_batch_sec": prog.get("last_batch_sec"),
                "verified_per_min": prog.get("verified_per_min"),
            }
        )

    gained_24h = (
        db.query(func.count(func.distinct(Offer.game_id)))
        .filter(Offer.last_verified_at.isnot(None), Offer.last_verified_at >= cut_24)
        .scalar()
        or 0
    )

    return {
        "generated_at": now.isoformat() + "Z",
        "day": _day_key(now),
        "total_games": total,
        "has_confirmed": confirmed,
        "confirmed_pct": round(100.0 * confirmed / total, 2) if total else 0.0,
        "states": dict(states),
        "games_with_verification_24h": gained_24h,
        "shops": shop_rows,
        "queue_dir": str(QUEUE_DIR),
        "note": "Admin-only; PE V2 confirmed coverage is authoritative for public catalog.",
    }


def save_coverage_snapshot(db: Session) -> dict[str, Any]:
    snap = build_coverage_snapshot(db)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"coverage-{snap['day']}.json"
    # Keep last write of the day (overwrite) plus timestamped copy.
    path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    ts_path = SNAPSHOT_DIR / f"coverage-{snap['day']}-{now_stamp()}.json"
    ts_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    snap["saved_to"] = str(path)
    return snap


def now_stamp() -> str:
    return _utcnow().strftime("%H%M%S")


def load_day_snapshot(day: str) -> dict[str, Any] | None:
    path = SNAPSHOT_DIR / f"coverage-{day}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def compare_coverage_days(db: Session, day_a: str, day_b: str | None = None) -> dict[str, Any]:
    a = load_day_snapshot(day_a)
    b = load_day_snapshot(day_b) if day_b else build_coverage_snapshot(db)
    if a is None:
        return {"ok": False, "error": f"missing snapshot for {day_a}"}
    if b is None:
        return {"ok": False, "error": f"missing snapshot for {day_b}"}
    return {
        "ok": True,
        "day_a": day_a,
        "day_b": day_b or b.get("day"),
        "confirmed_a": a.get("has_confirmed"),
        "confirmed_b": b.get("has_confirmed"),
        "confirmed_delta": int(b.get("has_confirmed") or 0) - int(a.get("has_confirmed") or 0),
        "pct_a": a.get("confirmed_pct"),
        "pct_b": b.get("confirmed_pct"),
        "states_a": a.get("states"),
        "states_b": b.get("states"),
    }
