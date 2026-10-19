"""V4: store coverage, import queue, approval preserve, demand-signal honesty."""
from __future__ import annotations

import json
from pathlib import Path

from tools.igdb_discovery.approval import ApprovalStore
from tools.igdb_discovery.classify import BUCKET_APPROVABLE, BUCKET_NEEDS_REVIEW, classify
from tools.igdb_discovery.fetchers import IgdbCandidate
from tools.igdb_discovery.import_queue import (
    QUEUE_EXISTS,
    QUEUE_HIGH,
    QUEUE_MANUAL,
    QUEUE_UPCOMING,
    assign_queue,
)
from tools.igdb_discovery.matching import MatchResult
from tools.igdb_discovery.staging import StagingStore
from tools.igdb_discovery.steam_verify import SteamCheck
from tools.igdb_discovery.store_coverage import LocalStoreIndex, StoreCoverageResult


def _cand(**kwargs) -> IgdbCandidate:
    base = dict(
        igdb_id=1,
        name="Test Game",
        slug="test-game",
        game_type=0,
        first_release_date=1_700_000_000,
        steam_appid=111,
        source="new_releases",
    )
    base.update(kwargs)
    return IgdbCandidate(**base)


def _new_match() -> MatchResult:
    return MatchResult(
        status="new_candidate",
        confidence=0.9,
        reason="steam_appid_absent_from_catalog",
        match_method="steam_appid",
    )


def _steam(**kwargs) -> SteamCheck:
    base = dict(
        steam_appid=111,
        available=True,
        unverified=False,
        steam_name="Test Game",
        app_type="game",
        title_ok=True,
        title_reason="exact",
        windows=True,
        is_free=False,
        coming_soon=False,
        release_date="2026-10-01",
        recommendations=None,
    )
    base.update(kwargs)
    return SteamCheck(**base)


def test_recs_none_not_labeled_too_few():
    v = classify(
        _cand(),
        _new_match(),
        _steam(recommendations=None),
        category="new_releases",
        metric_norm=None,
        steam_resolution_status="verified",
    )
    assert v.bucket == BUCKET_NEEDS_REVIEW
    assert v.reason == "insufficient_demand_signals"
    assert "not_equated_to_zero_reviews" in v.reasons


def test_paid_with_real_low_recs_still_needs_review():
    v = classify(
        _cand(),
        _new_match(),
        _steam(recommendations=2),
        category="new_releases",
        metric_norm=0.0,
        steam_resolution_status="verified",
    )
    assert v.bucket == BUCKET_NEEDS_REVIEW
    assert v.reason == "paid_but_too_few_steam_recommendations"


def test_popscore_allows_approvable_without_recs():
    v = classify(
        _cand(),
        _new_match(),
        _steam(recommendations=None),
        category="new_releases",
        metric_norm=0.8,
        steam_resolution_status="verified",
    )
    assert v.bucket == BUCKET_APPROVABLE


def test_import_queue_upcoming_and_exists():
    upcoming = {
        "in_quenly": False,
        "review": {"bucket": "APPROVABLE", "scan_priority": 10, "monetization": "unreleased"},
        "popularity": {"category": "upcoming"},
        "steam": {"coming_soon": True},
        "steam_resolution": {"status": "verified"},
    }
    assert assign_queue(upcoming).queue == QUEUE_UPCOMING

    exists = {
        "in_quenly": True,
        "review": {"bucket": "ALREADY_EXISTS", "scan_priority": 1},
        "popularity": {"category": "popular"},
        "steam": {},
        "steam_resolution": {"status": "verified"},
    }
    assert assign_queue(exists).queue == QUEUE_EXISTS

    amb = {
        "in_quenly": False,
        "review": {"bucket": "NEEDS_REVIEW", "scan_priority": 5, "reason": "x"},
        "popularity": {"category": "popular"},
        "steam": {},
        "steam_resolution": {"status": "ambiguous_manual_review"},
    }
    assert assign_queue(amb).queue == QUEUE_MANUAL


def test_high_priority_requires_tri_score_gate():
    row = {
        "in_quenly": False,
        "review": {
            "bucket": "APPROVABLE",
            "scan_priority": 90,
            "monetization": "paid",
            "pc_release_date": "2020-01-01",
        },
        "popularity": {"category": "trending"},
        "steam": {"coming_soon": False},
        "steam_resolution": {"status": "verified"},
    }
    # Without tri_score, V5 refuses HIGH_PRIORITY on category alone.
    assert assign_queue(row).queue == QUEUE_MANUAL
    row["tri_score"] = {
        "high_priority_eligible": True,
        "high_priority_reason": "demand_and_identity_confirmed",
        "demand": {"score": 70.0},
    }
    assert assign_queue(row).queue == QUEUE_HIGH


def test_store_coverage_unknown_not_absence(tmp_path: Path):
    idx = LocalStoreIndex(catalog_db=tmp_path / "missing.db", feeds_dir=tmp_path)
    cov = idx.lookup(igdb_id=1, name="Definitely Missing Title XYZ", steam_appid=999999001)
    assert isinstance(cov, StoreCoverageResult)
    assert cov.status == "unknown"
    assert "≠" in cov.summary or "UNKNOWN" in cov.summary.upper() or "no local" in cov.summary


def test_approval_preserve_across_upsert(tmp_path: Path):
    db = tmp_path / "stage.sqlite3"
    store = StagingStore(db)
    store.upsert_row(
        {
            "igdb_id": 42,
            "name": "Preserve Me",
            "match_status": "new_candidate",
            "source": "new_releases",
            "review_bucket": "APPROVABLE",
            "staging_status": "pending_review",
            "scan_priority": 10,
        }
    )
    appr = ApprovalStore(db)
    r1 = appr.decide(42, "approve", note="first")
    assert r1["ok"] and r1["new_status"] == "approved"
    r2 = appr.decide(42, "approve")
    assert not r2["ok"] and r2["error"] == "already_approved"

    # Re-upsert as pending_review must NOT wipe approval.
    store.upsert_row(
        {
            "igdb_id": 42,
            "name": "Preserve Me",
            "match_status": "new_candidate",
            "source": "new_releases",
            "review_bucket": "APPROVABLE",
            "staging_status": "pending_review",
            "scan_priority": 11,
            "import_queue": "HIGH_PRIORITY",
            "store_coverage_status": "unknown",
            "store_coverage_json": json.dumps({"status": "unknown"}),
        }
    )
    row = appr.get_candidate(42)
    assert row is not None
    assert row["staging_status"] == "approved"
    assert float(row["scan_priority"]) == 11.0
