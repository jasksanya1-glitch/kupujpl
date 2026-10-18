"""Per-shop independent scan queues with durable progress and rate limits.

Design goals (VPS / SQLite):
- Shops do not block each other (separate queues + budgets).
- Progress survives process restart (JSON under tmp/shop_queues/).
- Prefer stale offers first (updated_at ascending, nulls first).
- Global API concurrency cap; Playwright reserved but unused by default.
- No CAPTCHA bypass / fingerprint tricks — fail soft on 403/429.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import asc, case, desc, or_
from sqlalchemy.orm import Session

from app.core.database import BASE_DIR, SessionLocal
from app.core.offer_verification import (
    scan_v2_independent_workers,
    scan_v2_verification_enabled,
    shop_auth_blocker,
)
from app.core.offer_freshness import fresh_hours_for_shop
from app.models.models import Favorite, Game, Offer
from app.parsers.game_offers import refresh_offers_for_game
from app.parsers.shop_scan_config import get_active_scan_shops, get_shops_for_worker
from app.parsers.shop_scan_stats import ShopScanStats
from app.parsers.tier_a_top5000 import load_tier_a_cache

logger = logging.getLogger("shop_scan_queue")

QUEUE_DIR = Path(BASE_DIR) / "tmp" / "shop_queues"
LOCK_DIR = Path(BASE_DIR) / "tmp" / "shop_locks"
PID_PATH = Path(BASE_DIR) / "tmp" / "shop_scan_pipeline.pid"
HEARTBEAT_PATH = Path(BASE_DIR) / "tmp" / "shop_scan_pipeline.heartbeat"
REPORT_PATH = Path(BASE_DIR) / "tmp" / "shop_scan_report.json"

# Per-shop batch wall deadline (seconds). One hung shop must not own the process.
DEFAULT_SHOP_BATCH_DEADLINE_SEC = float(os.environ.get("SCAN_SHOP_BATCH_DEADLINE_SEC", "900"))
# Backoff before retrying auth_failed / rate_limited / blocked offers.
STATUS_BACKOFF_HOURS = float(os.environ.get("SCAN_STATUS_BACKOFF_HOURS", "6"))
# Fair scheduling: every Nth pick force oldest eligible (starvation protection).
STARVATION_EVERY = max(2, int(os.environ.get("SCAN_STARVATION_EVERY", "8")))

# Tier mix for catalog-wide recovery (must sum ~100). Tier A never starves Tier C.
TIER_A_BATCH_PCT = max(0, min(100, int(os.environ.get("SCAN_TIER_A_PCT", "55"))))
TIER_B_BATCH_PCT = max(0, min(100, int(os.environ.get("SCAN_TIER_B_PCT", "25"))))
TIER_C_BATCH_PCT = max(0, min(100, int(os.environ.get("SCAN_TIER_C_PCT", "20"))))
TIER_B_MIN_REVIEWS = int(os.environ.get("SCAN_TIER_B_MIN_REVIEWS", "500"))
TIER_A_MIN_REVIEWS = int(os.environ.get("SCAN_TIER_A_MIN_REVIEWS", "5000"))
# Only the hottest slice of the Tier-A sellers cache forces Tier A.
# Using the full 5000-entry cache as Tier A emptied the natural 500–4999
# review band (Tier B) — ~1178 of ~1183 mid-popularity games were swallowed.
TIER_A_CACHE_TOP_N = max(0, int(os.environ.get("SCAN_TIER_A_CACHE_TOP_N", "1000")))

# Global caps — keep site responsive on 8 vCPU / 16 GB.
GLOBAL_API_CONCURRENCY = max(1, int(os.environ.get("SCAN_GLOBAL_API_CONCURRENCY", "6")))
PLAYWRIGHT_PAGES = max(0, int(os.environ.get("SCAN_PLAYWRIGHT_PAGES", "0")))  # reserved
DEFAULT_SHOP_CONCURRENCY = max(1, int(os.environ.get("SCAN_SHOP_CONCURRENCY", "2")))
DEFAULT_SHOP_RPS = float(os.environ.get("SCAN_SHOP_RPS", "1.0"))

# Official / feed / Algolia shops can go a bit faster; HTML keyshops stay conservative.
# Steam RPS 2.5: measured ~2.0 sustainable; modest bump under load avg < 1 on 8 vCPU.
_SHOP_LIMITS: dict[str, dict[str, float]] = {
    "Steam": {"concurrency": 3, "rps": 2.5, "method": "api"},
    # concurrency > 1 hides HTTP latency under the same RPS budget (shared RateLimiter).
    "GOG": {"concurrency": 3, "rps": 1.5, "method": "api"},
    "Epic Games": {"concurrency": 3, "rps": 1.2, "method": "api"},
    "Instant Gaming": {"concurrency": 1, "rps": 0.5, "method": "html_api"},
    "Kinguin": {"concurrency": 2, "rps": 1.0, "method": "feed+html"},
    "Fanatical": {"concurrency": 1, "rps": 0.5, "method": "feed"},
    "G2A": {"concurrency": 1, "rps": 0.5, "method": "feed+html"},
    "Gamivo": {"concurrency": 1, "rps": 0.5, "method": "feed"},
    "CDKeys": {"concurrency": 1, "rps": 0.5, "method": "algolia"},
    "Eneba": {"concurrency": 1, "rps": 0.3, "method": "html"},
}


@dataclass
class ShopBudget:
    concurrency: int
    rps: float
    method: str


def shop_budget(shop: str) -> ShopBudget:
    raw = _SHOP_LIMITS.get(shop) or {}
    return ShopBudget(
        concurrency=int(raw.get("concurrency") or DEFAULT_SHOP_CONCURRENCY),
        rps=float(raw.get("rps") or DEFAULT_SHOP_RPS),
        method=str(raw.get("method") or "unknown"),
    )


def _queue_path(shop: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in shop)
    return QUEUE_DIR / f"{safe}.json"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_heartbeat(*, phase: str, detail: dict[str, Any] | None = None) -> None:
    payload = {
        "pid": os.getpid(),
        "phase": phase,
        "updated_at": datetime.utcnow().isoformat() + "Z",
        "detail": detail or {},
    }
    _write_json(HEARTBEAT_PATH, payload)


def write_pid() -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")


def clear_pid() -> None:
    PID_PATH.unlink(missing_ok=True)


def read_pipeline_pid() -> int | None:
    try:
        raw = PID_PATH.read_text(encoding="utf-8").strip()
        return int(raw)
    except (OSError, ValueError):
        return None


def is_pipeline_process_alive() -> bool:
    pid = read_pipeline_pid()
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def load_shop_progress(shop: str) -> dict[str, Any]:
    return _read_json(_queue_path(shop))


def save_shop_progress(shop: str, patch: dict[str, Any]) -> dict[str, Any]:
    state = load_shop_progress(shop)
    state.update(patch)
    state["shop"] = shop
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _write_json(_queue_path(shop), state)
    return state


def _shop_lock_path(shop: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in shop)
    return LOCK_DIR / f"{safe}.lock"


def try_acquire_shop_lock(shop: str) -> bool:
    """Non-blocking shop lock to prevent duplicate cycles for one shop."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    path = _shop_lock_path(shop)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()}\n{datetime.utcnow().isoformat()}Z\n")
        return True
    except FileExistsError:
        # Stale lock if owner PID is dead.
        try:
            raw = path.read_text(encoding="utf-8").splitlines()
            pid = int(raw[0]) if raw else 0
            os.kill(pid, 0)
            return False
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
            return try_acquire_shop_lock(shop)


def release_shop_lock(shop: str) -> None:
    _shop_lock_path(shop).unlink(missing_ok=True)


def _tier_a_rank_map() -> dict[int, int]:
    cache = load_tier_a_cache()
    games = cache.get("games") or []
    rank: dict[int, int] = {}
    for idx, g in enumerate(games):
        gid = g.get("game_id")
        if gid is None:
            continue
        rank[int(gid)] = idx
    return rank


def _favorite_game_ids(db: Session) -> set[int]:
    try:
        rows = db.query(Favorite.game_id).distinct().all()
        return {int(r[0]) for r in rows if r and r[0] is not None}
    except Exception:
        return set()


def _classify_scan_tier(
    gid: int,
    reviews: int,
    *,
    tier_rank: dict[int, int],
    favorite_ids: set[int],
    recommendations: int | None = None,
) -> str:
    """Mutually exclusive A/B/C by real popularity — not the full sellers list.

    Tier A: favorites, reviews >= TIER_A_MIN_REVIEWS, or rank in the top
    TIER_A_CACHE_TOP_N of the sellers cache (default 1000, not all 5000).
    Tier B: popularity score in [TIER_B_MIN_REVIEWS, TIER_A_MIN_REVIEWS).
    Tier C: everything else (incl. NULL/0 reviews).

    ``recommendations`` (Steam) may raise the popularity score when present so
    games with thin review counts but strong recs are not stuck in C forever.
    """
    rev = int(reviews or 0)
    recs = int(recommendations or 0)
    # Soft blend: recommendations are typically larger than review counts;
    # scale down so they inform but do not dominate the review ladder.
    popularity = max(rev, recs // 10) if recs > 0 else rev

    if gid in favorite_ids:
        return "A"
    if popularity >= TIER_A_MIN_REVIEWS:
        return "A"
    rank = tier_rank.get(gid)
    if rank is not None and TIER_A_CACHE_TOP_N > 0 and rank < TIER_A_CACHE_TOP_N:
        return "A"
    if popularity >= TIER_B_MIN_REVIEWS:
        return "B"
    return "C"


def select_stale_game_ids_for_shop(
    db: Session,
    shop: str,
    *,
    limit: int,
    after_game_id: int = 0,
    stale_hours: float | None = None,
    tier_a_only: bool = False,
) -> list[int]:
    """Fair stale selection across Tier A/B/C with aging / starvation protection.

    Default is a mixed catalog queue (not Tier-A-only). Uses last_verified_at when
    V2 columns exist; never invents verification timestamps. Rows with NULL
    last_verified_at and last_check_status not verified are always eligible
    (legacy upserts that never stamped verification).
    """
    # Align re-verify slightly inside PE fresh window so confirmed prices do not
    # expire between cycles (Steam/GOG/Epic default 36h → scan at 30h).
    if stale_hours is not None:
        hours = float(stale_hours)
    else:
        pe_fresh = float(fresh_hours_for_shop(shop))
        env_default = float(os.environ.get("SCAN_STALE_HOURS", str(max(12.0, pe_fresh * 0.85))))
        hours = env_default
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    backoff_cut = datetime.utcnow() - timedelta(hours=STATUS_BACKOFF_HOURS)
    use_v2 = scan_v2_verification_enabled()

    tier_rank = _tier_a_rank_map()
    favorite_ids = _favorite_game_ids(db)

    offer_cols = [Offer.game_id, Offer.updated_at, Offer.in_stock]
    if use_v2:
        offer_cols.extend(
            [Offer.last_verified_at, Offer.last_attempt_at, Offer.last_check_status]
        )
    subq = db.query(*offer_cols).filter(Offer.shop_name == shop).subquery()

    q = db.query(
        Game.id, Game.steam_review_count, Game.steam_recommendations
    ).outerjoin(subq, Game.id == subq.c.game_id)
    if tier_a_only:
        # Hot slice of sellers cache + favorites + high-review titles.
        hot_ids = {
            gid for gid, rank in tier_rank.items() if rank < TIER_A_CACHE_TOP_N
        } | set(favorite_ids)
        clauses = [Game.steam_review_count >= TIER_A_MIN_REVIEWS]
        if hot_ids:
            clauses.insert(0, Game.id.in_(hot_ids))
        q = q.filter(or_(*clauses))

    if use_v2:
        verified_for_order = case(
            (subq.c.last_verified_at.isnot(None), subq.c.last_verified_at),
            else_=subq.c.updated_at,
        )
        # Failed checks with NULL verification must re-enter the queue even if
        # updated_at was touched. Successful legacy rows (status verified/unset)
        # use updated_at age only — never invent last_verified_at here.
        failed_unchecked = (
            (subq.c.last_verified_at.is_(None))
            & (subq.c.last_check_status.isnot(None))
            & (subq.c.last_check_status != "")
            & (subq.c.last_check_status != "verified")
            & (subq.c.last_check_status != "skipped")
        )
        stale_pred = (
            (subq.c.game_id.is_(None))
            | (subq.c.in_stock.is_(False))
            | failed_unchecked
            | (
                (subq.c.last_verified_at.is_(None))
                & ((subq.c.updated_at.is_(None)) | (subq.c.updated_at < cutoff))
            )
            | (
                (subq.c.last_verified_at.isnot(None))
                & (subq.c.last_verified_at < cutoff)
            )
        )
    else:
        verified_for_order = subq.c.updated_at
        stale_pred = (
            (subq.c.game_id.is_(None))
            | (subq.c.in_stock.is_(False))
            | (subq.c.updated_at.is_(None))
            | (subq.c.updated_at < cutoff)
        )
    q = q.filter(stale_pred)

    if use_v2:
        # Include unavailable/error so repeated OOS / no-match (e.g. Instant
        # Gaming has_stock=0 on popular titles) rotate out for STATUS_BACKOFF_HOURS
        # instead of starving the rest of the catalog.
        bad = (
            "auth_failed",
            "rate_limited",
            "blocked",
            "unavailable",
            "error",
            "timeout",
        )
        q = q.filter(
            (subq.c.last_check_status.is_(None))
            | (~subq.c.last_check_status.in_(bad))
            | (subq.c.last_attempt_at.is_(None))
            | (subq.c.last_attempt_at < backoff_cut)
        )

    order = [
        case((subq.c.in_stock.is_(True), 0), else_=1),
        desc(Game.steam_review_count),
        asc(verified_for_order),
        Game.id.asc(),
    ]
    q = q.order_by(*order)

    fetch_n = max(limit * 6, limit + STARVATION_EVERY * 3, 120)
    review_by_id: dict[int, int] = {}
    if after_game_id > 0:
        fetched = [
            (gid, int(reviews or 0), int(recs or 0))
            for gid, reviews, recs in q.limit(fetch_n).all()
            if gid > after_game_id
        ]
    else:
        fetched = [
            (gid, int(reviews or 0), int(recs or 0))
            for gid, reviews, recs in q.limit(fetch_n).all()
        ]
    if not fetched:
        return []

    buckets: dict[str, list[int]] = {"A": [], "B": [], "C": []}
    for gid, reviews, recs in fetched:
        review_by_id[gid] = reviews
        tier = _classify_scan_tier(
            gid,
            reviews,
            tier_rank=tier_rank,
            favorite_ids=favorite_ids,
            recommendations=recs,
        )
        buckets[tier].append(gid)

    for tier, ids in buckets.items():
        ids.sort(
            key=lambda gid: (
                tier_rank.get(gid, 10_000) if tier == "A" else 0,
                -review_by_id.get(gid, 0),
                gid,
            )
        )

    # Normalize mix percentages.
    pct_sum = max(1, TIER_A_BATCH_PCT + TIER_B_BATCH_PCT + TIER_C_BATCH_PCT)
    quota = {
        "A": max(1, int(round(limit * TIER_A_BATCH_PCT / pct_sum))) if TIER_A_BATCH_PCT else 0,
        "B": max(1, int(round(limit * TIER_B_BATCH_PCT / pct_sum))) if TIER_B_BATCH_PCT else 0,
        "C": max(1, int(round(limit * TIER_C_BATCH_PCT / pct_sum))) if TIER_C_BATCH_PCT else 0,
    }
    # Ensure quotas fit limit.
    while sum(quota.values()) > limit:
        for t in ("A", "B", "C"):
            if quota[t] > 1 and sum(quota.values()) > limit:
                quota[t] -= 1

    out: list[int] = []
    seen: set[int] = set()
    pointers = {"A": 0, "B": 0, "C": 0}

    def _take(tier: str, n: int) -> None:
        taken = 0
        while taken < n and pointers[tier] < len(buckets[tier]) and len(out) < limit:
            gid = buckets[tier][pointers[tier]]
            pointers[tier] += 1
            if gid in seen:
                continue
            seen.add(gid)
            out.append(gid)
            taken += 1

    _take("A", quota["A"])
    _take("B", quota["B"])
    _take("C", quota["C"])
    # Fill remainder from any tier (A→B→C), then absolute oldest for aging.
    for tier in ("A", "B", "C"):
        _take(tier, limit)

    if len(out) < limit:
        leftover = [gid for gid, _reviews, _recs in fetched if gid not in seen]
        for gid in leftover:
            if len(out) >= limit:
                break
            seen.add(gid)
            out.append(gid)

    # Inject every Nth slot as absolute oldest for starvation protection.
    if len(out) >= STARVATION_EVERY and fetched:
        by_age = [gid for gid, _reviews, _recs in fetched]
        for i in range(STARVATION_EVERY - 1, len(out), STARVATION_EVERY):
            if i < len(by_age):
                aged = by_age[min(i, len(by_age) - 1)]
                if aged not in out[:i]:
                    out[i] = aged
    return out[:limit]


class _RateLimiter:
    def __init__(self, rps: float) -> None:
        self._min_interval = 1.0 / max(rps, 0.05)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next - now)
            self._next = max(now, self._next) + self._min_interval
        if delay:
            time.sleep(delay)


# Shared per-shop limiters — every HTTP call in a shop context must wait here so
# ThreadPool workers cannot multiply RPS via retries / product-page follow-ups.
_SHOP_LIMITERS_LOCK = threading.Lock()
_SHOP_LIMITERS: dict[str, _RateLimiter] = {}
_HTTP_SHOP_CTX = threading.local()


def shared_shop_limiter(shop: str) -> _RateLimiter:
    with _SHOP_LIMITERS_LOCK:
        lim = _SHOP_LIMITERS.get(shop)
        if lim is None:
            lim = _RateLimiter(shop_budget(shop).rps)
            _SHOP_LIMITERS[shop] = lim
        return lim


def set_shop_http_context(shop: str | None) -> None:
    _HTTP_SHOP_CTX.shop = shop


def shop_http_wait(shop: str | None = None) -> None:
    """Block until the next request slot for this shop (thread-safe)."""
    name = shop or getattr(_HTTP_SHOP_CTX, "shop", None)
    if not name:
        return
    shared_shop_limiter(str(name)).wait()


# Per-shop in-flight game IDs — prevent duplicate concurrent scans of same game.
_INFLIGHT_LOCK = threading.Lock()
_INFLIGHT: dict[str, set[int]] = {}


def _claim_inflight(shop: str, game_id: int) -> bool:
    with _INFLIGHT_LOCK:
        bag = _INFLIGHT.setdefault(shop, set())
        if game_id in bag:
            return False
        bag.add(game_id)
        return True


def _release_inflight(shop: str, game_id: int) -> None:
    with _INFLIGHT_LOCK:
        bag = _INFLIGHT.get(shop)
        if bag is not None:
            bag.discard(game_id)


def scan_shop_batch(
    shop: str,
    *,
    limit: int = 200,
    force: bool = False,
    stats: ShopScanStats | None = None,
    global_sema: threading.Semaphore | None = None,
    deadline_sec: float | None = None,
) -> dict[str, Any]:
    """Refresh up to `limit` stale games for one shop; persist progress.

    Hard batch deadline: returns with truncated=True instead of hanging forever.
    Auth-blocked shops exit immediately with status=auth_failed (no request storm).
    """
    if not try_acquire_shop_lock(shop):
        return {
            "phase": "skipped",
            "shop": shop,
            "message": "lock_held",
            "last_batch_size": 0,
        }

    budget = shop_budget(shop)
    progress = load_shop_progress(shop)
    cursor = int(progress.get("cursor_game_id") or 0)
    started = datetime.utcnow()
    deadline = time.monotonic() + float(
        deadline_sec
        if deadline_sec is not None
        else DEFAULT_SHOP_BATCH_DEADLINE_SEC
    )
    os.environ.setdefault("OFFER_REFRESH_INNER_SERIAL", "1")

    try:
        auth_reason = shop_auth_blocker(shop)
        if auth_reason and not force:
            return save_shop_progress(
                shop,
                {
                    "phase": "auth_failed",
                    "method": budget.method,
                    "last_batch_size": 0,
                    "last_batch_verified": 0,
                    "last_batch_errors": 0,
                    "last_check_status": "auth_failed",
                    "message": auth_reason[:200],
                    "batch_started_at": started.isoformat() + "Z",
                    "last_batch_sec": 0.0,
                },
            )

        save_shop_progress(
            shop,
            {
                "phase": "running",
                "method": budget.method,
                "started_at": progress.get("started_at") or started.isoformat() + "Z",
                "batch_started_at": started.isoformat() + "Z",
                "errors": int(progress.get("errors") or 0),
                "checked": int(progress.get("checked") or 0),
                "updated": int(progress.get("updated") or 0),
                "verified": int(progress.get("verified") or 0),
            },
        )

        # Do NOT page by max(game_id): fair mix is popularity-ordered, so an
        # id cursor skips most of the catalog and falsely reports no_stale_games.
        # Stale predicate already drops freshly verified rows from the next pick.
        db = SessionLocal()
        try:
            game_ids = select_stale_game_ids_for_shop(
                db, shop, limit=limit, after_game_id=0, tier_a_only=False
            )
        finally:
            db.close()

        if not game_ids:
            done_at = datetime.utcnow().isoformat() + "Z"
            return save_shop_progress(
                shop,
                {
                    "phase": "idle",
                    "cursor_game_id": 0,
                    "cycle_finished_at": done_at,
                    "last_batch_size": 0,
                    "last_batch_verified": 0,
                    "last_batch_sec": 0.0,
                    "message": "no_stale_games",
                    "cursor_mode": "disabled_popularity_order",
                },
            )

        limiter = shared_shop_limiter(shop)
        counters_lock = threading.Lock()
        checked = 0
        verified = 0
        price_changed = 0
        errors = 0
        last_id = cursor
        truncated = False
        workers = max(1, min(int(budget.concurrency), len(game_ids)))

        def _process_one(gid: int) -> None:
            nonlocal checked, verified, price_changed, errors, last_id
            if time.monotonic() >= deadline:
                return
            if not _claim_inflight(shop, gid):
                return
            do_heartbeat = False
            snap_checked = snap_verified = snap_changed = snap_errors = 0
            snap_last = gid
            try:
                set_shop_http_context(shop)
                # Per-request waits happen inside fetch_url / http_pool; one
                # upfront wait still spaces game starts under the same budget.
                limiter.wait()
                if global_sema is not None:
                    global_sema.acquire()
                try:
                    # Short reads; WAL + busy_timeout coordinate concurrent writers
                    # from refresh_offers_for_game (own SessionLocal per call).
                    before = SessionLocal()
                    try:
                        prev = (
                            before.query(Offer)
                            .filter(Offer.game_id == gid, Offer.shop_name == shop)
                            .first()
                        )
                        prev_verified = (
                            getattr(prev, "last_verified_at", None) if prev else None
                        )
                        prev_price = (
                            float(prev.price_pln)
                            if prev and prev.price_pln is not None
                            else None
                        )
                        prev_ts = prev.updated_at if prev else None
                    finally:
                        before.close()

                    refresh_offers_for_game(
                        gid,
                        force=True,
                        fill_missing=False,
                        shop_names=frozenset({shop}),
                    )

                    after = SessionLocal()
                    try:
                        row = (
                            after.query(Offer)
                            .filter(Offer.game_id == gid, Offer.shop_name == shop)
                            .first()
                        )
                        now_verified = (
                            getattr(row, "last_verified_at", None) if row else None
                        )
                        status = (
                            getattr(row, "last_check_status", None) if row else None
                        )
                        is_verified = False
                        if row and row.in_stock:
                            if now_verified is not None and now_verified != prev_verified:
                                is_verified = True
                            elif (
                                now_verified is None
                                and row.updated_at
                                and row.updated_at != prev_ts
                                and status in (None, "verified")
                            ):
                                is_verified = True
                        hit = False
                        changed = False
                        if is_verified:
                            hit = True
                            if prev_price is not None and row.price_pln is not None:
                                if abs(float(row.price_pln) - prev_price) > 1e-6:
                                    changed = True
                            elif prev_price is None and row.price_pln is not None:
                                changed = True
                    finally:
                        after.close()

                    with counters_lock:
                        checked += 1
                        last_id = max(last_id, gid)
                        if hit:
                            verified += 1
                            if changed:
                                price_changed += 1
                            if stats:
                                stats.record(shop, "hit")
                        else:
                            if stats:
                                stats.record(shop, "miss")
                        do_heartbeat = checked % 10 == 0
                        snap_checked = checked
                        snap_verified = verified
                        snap_changed = price_changed
                        snap_errors = errors
                        snap_last = last_id
                except Exception as exc:
                    with counters_lock:
                        errors += 1
                        checked += 1
                        last_id = max(last_id, gid)
                        do_heartbeat = checked % 10 == 0
                        snap_checked = checked
                        snap_verified = verified
                        snap_changed = price_changed
                        snap_errors = errors
                        snap_last = last_id
                    if stats:
                        stats.record(shop, "error", error=str(exc))
                    logger.warning("shop scan %s game %s failed: %s", shop, gid, exc)
                finally:
                    if global_sema is not None:
                        global_sema.release()

                if do_heartbeat:
                    save_shop_progress(
                        shop,
                        {
                            "phase": "running",
                            "cursor_game_id": snap_last,
                            "checked": int(progress.get("checked") or 0) + snap_checked,
                            "verified": int(progress.get("verified") or 0) + snap_verified,
                            "updated": int(progress.get("updated") or 0) + snap_changed,
                            "errors": int(progress.get("errors") or 0) + snap_errors,
                            "method": budget.method,
                            "workers": workers,
                        },
                    )
                    write_heartbeat(
                        phase="shop_batch",
                        detail={
                            "shop": shop,
                            "checked": snap_checked,
                            "verified": snap_verified,
                            "batch_limit": limit,
                            "workers": workers,
                        },
                    )
            finally:
                set_shop_http_context(None)
                _release_inflight(shop, gid)

        if workers <= 1:
            for gid in game_ids:
                if time.monotonic() >= deadline:
                    truncated = True
                    break
                _process_one(gid)
        else:
            # Bounded parallelism within shop RPS — hide HTTP latency, not multiply RPS.
            pending: set = set()
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"scan-{shop[:8]}") as pool:
                for gid in game_ids:
                    if time.monotonic() >= deadline:
                        truncated = True
                        break
                    fut = pool.submit(_process_one, gid)
                    pending.add(fut)
                    if len(pending) >= workers * 2:
                        done, pending = wait(pending, return_when=FIRST_COMPLETED)
                        for finished_fut in done:
                            finished_fut.result()
                if pending:
                    done, still = wait(pending, timeout=max(0.1, deadline - time.monotonic()))
                    for finished_fut in done:
                        finished_fut.result()
                    if still:
                        truncated = True
                        for leftover in still:
                            leftover.cancel()

        finished = datetime.utcnow()
        elapsed = round((finished - started).total_seconds(), 2)
        unchanged = max(0, verified - price_changed)
        try:
            from app.parsers.scanner_metrics import record_batch_metrics

            record_batch_metrics(
                shop,
                attempted=checked,
                verified=verified,
                unique_games=checked,
                price_unchanged=unchanged,
                errors=errors,
                timeouts=0,
                rate_limit_waits=checked,  # limiter.wait() once per game
                batch_sec=elapsed,
                http_requests=checked if shop == "Steam" else checked,
                http_ok=verified,
            )
        except Exception:
            logger.debug("scanner metrics write failed for %s", shop, exc_info=True)
        out = save_shop_progress(
            shop,
            {
                "phase": "truncated" if truncated else "running",
                # Keep for diagnostics only — not used for selection paging.
                "cursor_game_id": 0,
                "last_batch_max_game_id": last_id,
                "checked": int(progress.get("checked") or 0) + checked,
                "verified": int(progress.get("verified") or 0) + verified,
                "updated": int(progress.get("updated") or 0) + price_changed,
                "errors": int(progress.get("errors") or 0) + errors,
                "last_batch_size": checked,
                "last_batch_verified": verified,
                "last_batch_updated": price_changed,
                "last_batch_unchanged": unchanged,
                "last_batch_errors": errors,
                "last_batch_sec": elapsed,
                "verified_per_min": round(60.0 * verified / elapsed, 2) if elapsed else 0.0,
                "verified_per_hour_est": round(3600.0 * verified / elapsed, 1) if elapsed else 0.0,
                "method": budget.method,
                "workers": workers,
                "rps_budget": budget.rps,
                "truncated": truncated,
                "cursor_mode": "disabled_popularity_order",
            },
        )
        write_heartbeat(
            phase="shop_batch",
            detail={
                "shop": shop,
                "checked": checked,
                "verified": verified,
                "workers": workers,
            },
        )
        return out
    finally:
        release_shop_lock(shop)


def run_shop_scan_cycle(
    *,
    shops: list[str] | None = None,
    batch_per_shop: int = 150,
    max_seconds: int | None = None,
) -> dict[str, Any]:
    """Coordinated multi-shop cycle with independent deadlines per shop."""
    write_pid()
    write_heartbeat(phase="start")
    started = time.monotonic()
    active = list(shops or get_shops_for_worker("vps") or get_active_scan_shops())
    stats = ShopScanStats()
    sema = threading.Semaphore(GLOBAL_API_CONCURRENCY)
    report: dict[str, Any] = {
        "started_at": datetime.utcnow().isoformat() + "Z",
        "shops": {},
        "global_api_concurrency": GLOBAL_API_CONCURRENCY,
        "playwright_pages": PLAYWRIGHT_PAGES,
        "scan_v2": scan_v2_independent_workers(),
    }

    try:
        order_rank = {
            "Steam": 0,
            "GOG": 1,
            "Epic Games": 2,
            "Kinguin": 3,
            "Fanatical": 4,
            "CDKeys": 5,
            "Instant Gaming": 6,
            "G2A": 7,
            "Gamivo": 8,
            "Eneba": 9,
        }
        ordered = sorted(active, key=lambda s: order_rank.get(s, 50))

        # Independent workers: up to 3 shops in parallel; each has own deadline.
        shop_workers = max(1, min(3, len(ordered)))
        per_shop_deadline = DEFAULT_SHOP_BATCH_DEADLINE_SEC
        if max_seconds:
            per_shop_deadline = min(per_shop_deadline, float(max_seconds))

        pool = ThreadPoolExecutor(max_workers=shop_workers)
        try:
            futs = {
                pool.submit(
                    scan_shop_batch,
                    shop,
                    limit=batch_per_shop,
                    stats=stats,
                    global_sema=sema,
                    deadline_sec=per_shop_deadline,
                ): shop
                for shop in ordered
            }
            pending = set(futs)
            while pending:
                remaining = None
                if max_seconds:
                    remaining = max(0.1, max_seconds - (time.monotonic() - started))
                    if (time.monotonic() - started) >= max_seconds:
                        break
                done, pending = wait(
                    pending,
                    timeout=remaining,
                    return_when=FIRST_COMPLETED,
                )
                if not done:
                    break
                for fut in done:
                    shop = futs[fut]
                    try:
                        report["shops"][shop] = fut.result(timeout=1)
                    except Exception as exc:
                        report["shops"][shop] = {
                            "phase": "failed",
                            "error": str(exc)[:200],
                        }
                if max_seconds and (time.monotonic() - started) >= max_seconds:
                    break
            if pending:
                report["truncated"] = True
                report["pending_shops"] = [futs[f] for f in pending]
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        report["stats"] = stats.to_dict()
        report["finished_at"] = datetime.utcnow().isoformat() + "Z"
        report["duration_sec"] = round(time.monotonic() - started, 1)
        _write_json(REPORT_PATH, report)
        write_heartbeat(phase="done", detail={"duration_sec": report["duration_sec"]})
        return report
    finally:
        clear_pid()


def build_freshness_snapshot(db: Session | None = None) -> dict[str, Any]:
    """In-stock verified freshness. Prefer last_verified_at when V2 is on."""
    own = db is None
    if own:
        db = SessionLocal()
    assert db is not None
    try:
        now = datetime.utcnow()
        use_v2 = scan_v2_verification_enabled()
        if use_v2:
            rows = db.query(
                Offer.shop_name,
                Offer.updated_at,
                Offer.in_stock,
                Offer.last_verified_at,
                Offer.last_check_status,
            ).all()
        else:
            rows = db.query(Offer.shop_name, Offer.updated_at, Offer.in_stock).all()

        by: dict[str, dict[str, int]] = {}
        for row in rows:
            if use_v2:
                shop, updated, in_stock, last_verified, status = row
            else:
                shop, updated, in_stock = row
                last_verified, status = None, None
            d = by.setdefault(
                shop,
                {
                    "n": 0,
                    "stock": 0,
                    "h24": 0,
                    "h48": 0,
                    "h24_all": 0,
                    "h48_all": 0,
                    "verified_known": 0,
                },
            )
            d["n"] += 1
            if in_stock:
                d["stock"] += 1
            # Verified timestamp only — never count failed attempts as fresh.
            ts = None
            if use_v2 and last_verified is not None:
                ts = last_verified
                if in_stock:
                    d["verified_known"] += 1
            elif use_v2 and status not in (None, "", "verified"):
                ts = None  # failed attempt must not inflate freshness
            else:
                # Legacy row (no V2 verify yet): fall back to updated_at only.
                ts = updated
            if not ts:
                continue
            if getattr(ts, "tzinfo", None):
                ts = ts.replace(tzinfo=None)
            age_h = (now - ts).total_seconds() / 3600.0
            if age_h <= 24:
                d["h24_all"] += 1
                if in_stock:
                    d["h24"] += 1
            if age_h <= 48:
                d["h48_all"] += 1
                if in_stock:
                    d["h48"] += 1
        stock = sum(v["stock"] for v in by.values()) or 1
        h24 = sum(v["h24"] for v in by.values())
        h48 = sum(v["h48"] for v in by.values())
        return {
            "generated_at": now.isoformat() + "Z",
            "metric": "last_verified_at" if use_v2 else "updated_at_legacy",
            "in_stock_total": stock,
            "fresh_24h": h24,
            "fresh_24h_pct": round(100.0 * h24 / stock, 2),
            "fresh_48h": h48,
            "fresh_48h_pct": round(100.0 * h48 / stock, 2),
            "fresh_24h_all_offers": sum(v["h24_all"] for v in by.values()),
            "shops": by,
        }
    finally:
        if own:
            db.close()
