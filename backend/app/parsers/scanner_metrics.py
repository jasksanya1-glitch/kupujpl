"""Per-shop scanner timing metrics (persisted JSON for coverage monitor)."""
from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.database import BASE_DIR

METRICS_DIR = Path(BASE_DIR) / "tmp" / "scanner_metrics"
_LOCK = threading.Lock()
_HOUR_BUCKETS: dict[str, dict[str, float | int]] = defaultdict(dict)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hour_key(dt: datetime | None = None) -> str:
    return (dt or _utcnow()).strftime("%Y-%m-%dT%H")


def _shop_path(shop: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in shop)
    return METRICS_DIR / f"{safe}.json"


def record_batch_metrics(
    shop: str,
    *,
    attempted: int,
    verified: int,
    unique_games: int,
    price_unchanged: int,
    errors: int,
    timeouts: int,
    rate_limit_waits: int,
    batch_sec: float,
    http_sec: float = 0.0,
    db_sec: float = 0.0,
    idle_sec: float = 0.0,
    queue_wait_sec: float = 0.0,
    http_requests: int = 0,
    http_ok: int = 0,
) -> dict[str, Any]:
    """Accumulate into the current hour bucket and persist."""
    hour = _hour_key()
    with _LOCK:
        bucket = _HOUR_BUCKETS.setdefault(shop, {})
        if bucket.get("hour") != hour:
            _flush_unlocked(shop, bucket)
            bucket.clear()
            bucket["hour"] = hour
            bucket["shop"] = shop
        for key, val in {
            "attempted": attempted,
            "verified": verified,
            "unique_games": unique_games,
            "price_unchanged": price_unchanged,
            "errors": errors,
            "timeouts": timeouts,
            "rate_limit_waits": rate_limit_waits,
            "batch_sec": batch_sec,
            "http_sec": http_sec,
            "db_sec": db_sec,
            "idle_sec": idle_sec,
            "queue_wait_sec": queue_wait_sec,
            "http_requests": http_requests,
            "http_ok": http_ok,
            "batches": 1,
        }.items():
            bucket[key] = float(bucket.get(key) or 0) + float(val)
        bucket["updated_at"] = _utcnow().isoformat() + "Z"
        verified_n = float(bucket.get("verified") or 0)
        batch_t = float(bucket.get("batch_sec") or 0)
        bucket["verified_per_hour_est"] = round(
            verified_n / (batch_t / 3600.0), 2
        ) if batch_t > 0 else 0.0
        _write_unlocked(shop, bucket)
        return dict(bucket)


def record_idle(shop: str, idle_sec: float) -> None:
    hour = _hour_key()
    with _LOCK:
        bucket = _HOUR_BUCKETS.setdefault(shop, {})
        if bucket.get("hour") != hour:
            _flush_unlocked(shop, bucket)
            bucket.clear()
            bucket["hour"] = hour
            bucket["shop"] = shop
        bucket["idle_sec"] = float(bucket.get("idle_sec") or 0) + float(idle_sec)
        bucket["updated_at"] = _utcnow().isoformat() + "Z"
        _write_unlocked(shop, bucket)


def _write_unlocked(shop: str, bucket: dict[str, Any]) -> None:
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    path = _shop_path(shop)
    path.write_text(json.dumps(bucket, indent=2), encoding="utf-8")


def _flush_unlocked(shop: str, bucket: dict[str, Any]) -> None:
    if not bucket or not bucket.get("hour"):
        return
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    hist = METRICS_DIR / f"{_shop_path(shop).stem}-{bucket['hour']}.json"
    hist.write_text(json.dumps(bucket, indent=2), encoding="utf-8")


def load_shop_metrics(shop: str) -> dict[str, Any]:
    path = _shop_path(shop)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


class PhaseTimer:
    """Simple monotonic phase timer for one game/batch."""

    def __init__(self) -> None:
        self.t0 = time.monotonic()
        self.marks: dict[str, float] = {}

    def mark(self, name: str) -> None:
        self.marks[name] = time.monotonic() - self.t0

    def since(self, name: str) -> float:
        return float(self.marks.get(name) or 0.0)
