"""Local PopScore snapshots for trending deltas (7d / 30d).

IGDB primitives are point-in-time; without history we cannot claim TRENDING.
Snapshots live only in isolated staging SQLite.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import config

SNAP_DB = config.STAGING_DIR / "pop_score_history.sqlite3"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _init(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pop_snapshots (
              day TEXT NOT NULL,
              popularity_type INTEGER NOT NULL,
              game_id INTEGER NOT NULL,
              value REAL NOT NULL,
              PRIMARY KEY (day, popularity_type, game_id)
            )
            """
        )


def record_snapshot(
    popularity_type: int,
    pairs: list[tuple[int, float]],
    *,
    day: str | None = None,
) -> str:
    _init(SNAP_DB)
    day = day or _utcnow().date().isoformat()
    with sqlite3.connect(SNAP_DB) as con:
        con.executemany(
            "INSERT INTO pop_snapshots(day,popularity_type,game_id,value) VALUES(?,?,?,?) "
            "ON CONFLICT(day,popularity_type,game_id) DO UPDATE SET value=excluded.value",
            [(day, int(popularity_type), int(gid), float(val)) for gid, val in pairs],
        )
    return day


def load_day(popularity_type: int, day: str) -> dict[int, float]:
    if not SNAP_DB.is_file():
        return {}
    with sqlite3.connect(SNAP_DB) as con:
        rows = con.execute(
            "SELECT game_id, value FROM pop_snapshots WHERE popularity_type=? AND day=?",
            (int(popularity_type), day),
        ).fetchall()
    return {int(g): float(v) for g, v in rows}


def nearest_day_before(popularity_type: int, before_day: str, *, within_days: int) -> str | None:
    if not SNAP_DB.is_file():
        return None
    target = datetime.fromisoformat(before_day).date()
    oldest = (target - timedelta(days=within_days)).isoformat()
    with sqlite3.connect(SNAP_DB) as con:
        row = con.execute(
            "SELECT day FROM pop_snapshots WHERE popularity_type=? AND day<? AND day>=? "
            "ORDER BY day DESC LIMIT 1",
            (int(popularity_type), before_day, oldest),
        ).fetchone()
    return row[0] if row else None


def trending_deltas(
    popularity_type: int,
    today_pairs: list[tuple[int, float]],
) -> dict[str, Any]:
    """Compute 7d/30d growth; mark insufficient_history when baselines missing."""
    today = record_snapshot(popularity_type, today_pairs)
    today_map = dict(today_pairs)
    day7 = nearest_day_before(popularity_type, today, within_days=10)
    day30 = nearest_day_before(popularity_type, today, within_days=40)
    base7 = load_day(popularity_type, day7) if day7 else {}
    base30 = load_day(popularity_type, day30) if day30 else {}

    growth: dict[int, dict[str, float | None]] = {}
    for gid, val in today_map.items():
        g7 = None
        g30 = None
        if day7 and gid in base7 and base7[gid] > 0:
            g7 = (val - base7[gid]) / base7[gid]
        elif day7 and gid in base7:
            g7 = val - base7[gid]
        if day30 and gid in base30 and base30[gid] > 0:
            g30 = (val - base30[gid]) / base30[gid]
        elif day30 and gid in base30:
            g30 = val - base30[gid]
        growth[gid] = {"d7": g7, "d30": g30, "today": val}

    return {
        "today": today,
        "baseline_7d": day7,
        "baseline_30d": day30,
        "insufficient_history": day7 is None and day30 is None,
        "growth": growth,
    }
