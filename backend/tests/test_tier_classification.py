"""Tier A/B/C must reflect real popularity — not swallow mid-band into A via full cache."""
from __future__ import annotations

from app.parsers.shop_scan_queue import (
    TIER_A_CACHE_TOP_N,
    TIER_A_MIN_REVIEWS,
    TIER_B_MIN_REVIEWS,
    _classify_scan_tier,
)


def test_thresholds_are_mutually_exclusive_bands():
    assert TIER_B_MIN_REVIEWS < TIER_A_MIN_REVIEWS
    assert TIER_A_CACHE_TOP_N > 0
    assert TIER_A_CACHE_TOP_N < 5000  # must not use entire sellers list as Tier A


def test_null_and_zero_reviews_are_tier_c():
    empty: dict[int, int] = {}
    favs: set[int] = set()
    assert _classify_scan_tier(1, 0, tier_rank=empty, favorite_ids=favs) == "C"
    assert _classify_scan_tier(1, None, tier_rank=empty, favorite_ids=favs) == "C"  # type: ignore[arg-type]


def test_mid_band_reviews_are_tier_b_not_full_cache_a():
    # Game ranked #2500 in sellers cache must NOT become A solely for that.
    tier_rank = {42: 2500}
    favs: set[int] = set()
    assert (
        _classify_scan_tier(42, 800, tier_rank=tier_rank, favorite_ids=favs) == "B"
    )


def test_hot_cache_slice_is_tier_a():
    tier_rank = {7: 50}  # inside default top-1000
    assert _classify_scan_tier(7, 10, tier_rank=tier_rank, favorite_ids=set()) == "A"


def test_high_reviews_are_tier_a_without_cache():
    assert (
        _classify_scan_tier(9, 12_000, tier_rank={}, favorite_ids=set()) == "A"
    )


def test_favorites_are_tier_a():
    assert (
        _classify_scan_tier(3, 0, tier_rank={}, favorite_ids={3}) == "A"
    )


def test_recommendations_can_lift_into_tier_b():
    # 400 reviews alone → C; 6000 recommendations → popularity 600 → B
    assert (
        _classify_scan_tier(
            11, 400, tier_rank={}, favorite_ids=set(), recommendations=6000
        )
        == "B"
    )


def test_coverage_monitor_uses_same_classifier():
    import inspect

    from app.core import coverage_monitor as cm

    src = inspect.getsource(cm.build_coverage_snapshot)
    assert "_classify_scan_tier" in src
    assert "gid in tier_rank or gid in favs" not in src
