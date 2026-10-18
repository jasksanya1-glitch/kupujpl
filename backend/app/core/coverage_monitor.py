"""Auth-gated catalog price coverage snapshots (hourly + daily)."""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import BASE_DIR
from app.core.price_engine import best_offers_map_v2
from app.models.models import Game, Offer
from app.parsers.scanner_metrics import load_shop_metrics
from app.parsers.shop_scan_queue import (
    QUEUE_DIR,
    _classify_scan_tier,
    _favorite_game_ids,
    _tier_a_rank_map,
    load_shop_progress,
)

SNAPSHOT_DIR = Path(BASE_DIR) / "tmp" / "coverage_snapshots"
HOURLY_DIR = SNAPSHOT_DIR / "hourly"
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


def _hour_key(dt: datetime | None = None) -> str:
    return (dt or _utcnow()).strftime("%Y-%m-%dT%H")


def _host_load_snapshot() -> dict[str, Any]:
    """Best-effort CPU/RAM for hourly snapshots (Linux /proc)."""
    out: dict[str, Any] = {"source": "unavailable"}
    try:
        load1, load5, load15 = os.getloadavg()  # type: ignore[attr-defined]
        out["loadavg"] = [round(load1, 2), round(load5, 2), round(load15, 2)]
        out["source"] = "getloadavg"
    except Exception:
        pass
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        kv = {}
        for line in meminfo.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                kv[k.strip()] = v.strip()
        def _kb(name: str) -> int | None:
            raw = kv.get(name, "")
            parts = raw.split()
            return int(parts[0]) if parts and parts[0].isdigit() else None
        total = _kb("MemTotal")
        avail = _kb("MemAvailable")
        if total and avail is not None:
            out["mem_total_mb"] = round(total / 1024)
            out["mem_available_mb"] = round(avail / 1024)
            out["mem_used_mb"] = round((total - avail) / 1024)
            out["source"] = "proc"
    except Exception:
        pass
    return out


def build_coverage_snapshot(db: Session) -> dict[str, Any]:
    """Read-only coverage + scanner effectiveness (confirmed ≠ any verify)."""
    now = _utcnow()
    cut_1 = now - timedelta(hours=1)
    cut_24 = now - timedelta(hours=24)
    cut_72 = now - timedelta(hours=72)

    games = db.query(Game).filter(Game.slug.isnot(None)).all()
    ids = [g.id for g in games]
    confirmed_map = best_offers_map_v2(db, ids) if ids else {}
    tier_rank = _tier_a_rank_map()
    favs = _favorite_game_ids(db)

    states = Counter()
    tier_total = Counter()
    tier_confirmed = Counter()
    paid_total = 0
    paid_confirmed = 0

    for g in games:
        reviews = int(g.steam_review_count or 0)
        recs = int(getattr(g, "steam_recommendations", None) or 0)
        tier = _classify_scan_tier(
            g.id,
            reviews,
            tier_rank=tier_rank,
            favorite_ids=favs,
            recommendations=recs,
        )
        if bool(getattr(g, "is_free", False)):
            states["free"] += 1
            continue
        paid_total += 1
        tier_total[tier] += 1
        if confirmed_map.get(g.id) is not None:
            states["has_confirmed"] += 1
            tier_confirmed[tier] += 1
            paid_confirmed += 1
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

        def _vcount(cut: datetime) -> int:
            return (
                db.query(func.count(Offer.id))
                .filter(
                    Offer.shop_name == shop,
                    Offer.last_verified_at.isnot(None),
                    Offer.last_verified_at >= cut,
                    Offer.last_check_status == "verified",
                )
                .scalar()
                or 0
            )

        v1, v24, v72 = _vcount(cut_1), _vcount(cut_24), _vcount(cut_72)
        unique_24 = (
            db.query(func.count(func.distinct(Offer.game_id)))
            .filter(
                Offer.shop_name == shop,
                Offer.last_verified_at.isnot(None),
                Offer.last_verified_at >= cut_24,
                Offer.last_check_status == "verified",
            )
            .scalar()
            or 0
        )
        stale_backlog = max(0, in_stock - v24)
        vph = round(v24 / 24.0, 2)
        eta_h = round(stale_backlog / vph, 1) if vph > 0 else None
        prog = load_shop_progress(shop)
        metrics = load_shop_metrics(shop)
        err_n = int(prog.get("errors") or 0)
        checked_n = int(prog.get("checked") or 1)
        msg = str(prog.get("message") or "")
        # Post-fix idle with cursor_mode disabled should not report false empties.
        # Count residual "no_stale_games" while cursor_mode still looks legacy.
        false_empty_hint = (
            msg == "no_stale_games"
            and str(prog.get("cursor_mode") or "") != "disabled_popularity_order"
            and int(prog.get("last_batch_size") or 0) == 0
        )
        unique_1h = (
            db.query(func.count(func.distinct(Offer.game_id)))
            .filter(
                Offer.shop_name == shop,
                Offer.last_verified_at.isnot(None),
                Offer.last_verified_at >= cut_1,
                Offer.last_check_status == "verified",
            )
            .scalar()
            or 0
        )
        shop_rows.append(
            {
                "shop": shop,
                "in_stock_priced": in_stock,
                "verified_1h": v1,
                "verified_24h": v24,
                "verified_72h": v72,
                "unique_games_verified_1h": unique_1h,
                "unique_games_verified_24h": unique_24,
                "stale_backlog_est": stale_backlog,
                "verified_per_hour_est": vph,
                "eta_hours_to_clear_backlog": eta_h,
                "error_rate_lifetime_pct": round(100.0 * err_n / checked_n, 2),
                "queue_phase": prog.get("phase"),
                "queue_message": msg[:160],
                "queue_idle_hint": (prog.get("phase") or "") == "idle",
                "false_empty_queue_hint": false_empty_hint,
                "cursor_mode": prog.get("cursor_mode"),
                "last_batch_verified": prog.get("last_batch_verified"),
                "last_batch_sec": prog.get("last_batch_sec"),
                "verified_per_min": prog.get("verified_per_min"),
                "verified_per_hour_batch": prog.get("verified_per_hour_est"),
                "live_metrics": metrics,
            }
        )

    gained_24h = (
        db.query(func.count(func.distinct(Offer.game_id)))
        .filter(
            Offer.last_verified_at.isnot(None),
            Offer.last_verified_at >= cut_24,
            Offer.last_check_status == "verified",
        )
        .scalar()
        or 0
    )

    def _tier_pct(t: str) -> float:
        tot = int(tier_total.get(t) or 0)
        conf = int(tier_confirmed.get(t) or 0)
        return round(100.0 * conf / tot, 2) if tot else 0.0

    return {
        "generated_at": now.isoformat() + "Z",
        "day": _day_key(now),
        "hour": _hour_key(now),
        "total_games": total,
        "has_confirmed": confirmed,
        "confirmed_pct_all_games": round(100.0 * confirmed / total, 2) if total else 0.0,
        "paid_games": paid_total,
        "paid_confirmed": paid_confirmed,
        "paid_confirmed_pct": round(100.0 * paid_confirmed / paid_total, 2) if paid_total else 0.0,
        "f2p_excluded": int(states.get("free", 0)),
        "states": dict(states),
        "tier_coverage": {
            "A": {
                "games": int(tier_total["A"]),
                "confirmed": int(tier_confirmed["A"]),
                "pct": _tier_pct("A"),
            },
            "B": {
                "games": int(tier_total["B"]),
                "confirmed": int(tier_confirmed["B"]),
                "pct": _tier_pct("B"),
            },
            "C": {
                "games": int(tier_total["C"]),
                "confirmed": int(tier_confirmed["C"]),
                "pct": _tier_pct("C"),
            },
        },
        "games_with_verification_24h": gained_24h,
        "shops": shop_rows,
        "false_empty_queue_shops": [
            r["shop"] for r in shop_rows if r.get("false_empty_queue_hint")
        ],
        "host": _host_load_snapshot(),
        "queue_dir": str(QUEUE_DIR),
        "baseline_ref": {
            "paid_games": 10414,
            "paid_confirmed": 2225,
            "paid_confirmed_pct": 21.37,
            "note": "bottleneck-final canary baseline 2026-10-18",
        },
        "note": (
            "Admin-only. confirmed = PE V2 confirmed prices only; "
            "verification counts are separate. Sustained throughput needs "
            "multi-hour history — single canary is not enough. "
            "LONG-TERM status stays PENDING until 48–72h of hourly snapshots exist."
        ),
    }


def save_coverage_snapshot(db: Session, *, hourly: bool = True) -> dict[str, Any]:
    snap = build_coverage_snapshot(db)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    day_path = SNAPSHOT_DIR / f"coverage-{snap['day']}.json"
    day_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    if hourly:
        HOURLY_DIR.mkdir(parents=True, exist_ok=True)
        hour_path = HOURLY_DIR / f"coverage-{snap['hour']}.json"
        hour_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
        snap["hourly_saved_to"] = str(hour_path)
    snap["saved_to"] = str(day_path)
    return snap


def load_day_snapshot(day: str) -> dict[str, Any] | None:
    path = SNAPSHOT_DIR / f"coverage-{day}.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_hour_snapshot(hour: str) -> dict[str, Any] | None:
    path = HOURLY_DIR / f"coverage-{hour}.json"
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
        "paid_pct_a": a.get("paid_confirmed_pct"),
        "paid_pct_b": b.get("paid_confirmed_pct"),
        "tier_a": a.get("tier_coverage"),
        "tier_b": b.get("tier_coverage"),
        "states_a": a.get("states"),
        "states_b": b.get("states"),
    }
