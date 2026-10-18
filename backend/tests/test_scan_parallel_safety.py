"""Bounded parallel shop batches: RPS shared, no duplicate in-flight games."""
from __future__ import annotations

import threading
import time

from app.parsers.shop_scan_queue import (
    _RateLimiter,
    _claim_inflight,
    _release_inflight,
    shop_budget,
)


def test_rate_limiter_never_exceeds_budget():
    lim = _RateLimiter(10.0)  # 10 rps → min 0.1s gap
    stamps: list[float] = []
    lock = threading.Lock()

    def hit() -> None:
        lim.wait()
        with lock:
            stamps.append(time.monotonic())

    threads = [threading.Thread(target=hit) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    stamps.sort()
    gaps = [stamps[i] - stamps[i - 1] for i in range(1, len(stamps))]
    assert gaps, "expected multiple stamps"
    # Allow tiny scheduling jitter below the theoretical floor.
    assert min(gaps) >= 0.08


def test_inflight_rejects_duplicate_game():
    shop = "_test_parallel_shop"
    assert _claim_inflight(shop, 101) is True
    assert _claim_inflight(shop, 101) is False
    assert _claim_inflight(shop, 102) is True
    _release_inflight(shop, 101)
    assert _claim_inflight(shop, 101) is True
    _release_inflight(shop, 101)
    _release_inflight(shop, 102)


def test_shop_budgets_do_not_multiply_rps_via_concurrency():
    """Concurrency hides latency; RPS remains the request budget."""
    steam = shop_budget("Steam")
    assert steam.concurrency >= 1
    assert steam.rps <= 3.0  # hard ceiling — do not silently hike
    gog = shop_budget("GOG")
    assert gog.concurrency <= 3
    assert gog.rps <= 2.0
