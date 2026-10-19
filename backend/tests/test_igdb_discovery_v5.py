"""V5: approval lanes, tri-score, rankings isolation, store sample labels."""
from __future__ import annotations

import json
from pathlib import Path

from tools.igdb_discovery.approval import (
    LANE_STAGING,
    LANE_TEST,
    ApprovalStore,
)
from tools.igdb_discovery.fetchers import IgdbCandidate
from tools.igdb_discovery.popularity import ScoredCandidate
from tools.igdb_discovery.scoring_v5 import (
    audit_five_nights_style_legacy,
    compute_tri_score,
)
from tools.igdb_discovery.staging import StagingStore
from tools.igdb_discovery.store_coverage import analyze_candidates


def test_simulation_approve_blocked_on_staging_db(tmp_path: Path):
    db = tmp_path / "staging.sqlite3"
    store = StagingStore(db)
    store.upsert_row(
        {
            "igdb_id": 1,
            "name": "Game",
            "match_status": "new_candidate",
            "source": "popular",
            "staging_status": "pending_review",
        }
    )
    appr = ApprovalStore(db, lane=LANE_STAGING)
    blocked = appr.decide(1, "approve", actor="daily_sim_probe", note="daily_sim_probe")
    assert not blocked["ok"]
    assert blocked["error"] == "simulation_approve_blocked_on_staging"


def test_simulation_approve_ok_on_test_lane(tmp_path: Path):
    db = tmp_path / "test.sqlite3"
    StagingStore(db).upsert_row(
        {
            "igdb_id": 2,
            "name": "Test Game",
            "match_status": "new_candidate",
            "source": "new_releases",
            "staging_status": "pending_review",
        }
    )
    appr = ApprovalStore(db, lane=LANE_TEST)
    ok = appr.decide(2, "approve", actor="daily_sim_probe", note="daily_sim_probe")
    assert ok["ok"]
    assert ok["lane"] == LANE_TEST


def test_revoke_keeps_log_history(tmp_path: Path):
    db = tmp_path / "stage.sqlite3"
    StagingStore(db).upsert_row(
        {
            "igdb_id": 370112,
            "name": "PUBG: Black Budget",
            "match_status": "new_candidate",
            "source": "trending",
            "staging_status": "pending_review",
            "approval_note": "daily_sim_probe",
            "approval_class": "simulation",
        }
    )
    appr = ApprovalStore(db, lane=LANE_TEST)
    appr.decide(370112, "approve", actor="daily_sim_probe", note="daily_sim_probe")
    rev = appr.revoke_simulation_approval(370112, note="controlled revoke")
    assert rev["ok"]
    row = appr.get_candidate(370112)
    assert row["staging_status"] == "pending_review"
    log = appr.recent_log(10)
    actions = [e["action"] for e in log if e["igdb_id"] == 370112]
    assert "approve" in actions and "revoke" in actions


def test_refuse_revoke_human(tmp_path: Path):
    db = tmp_path / "stage.sqlite3"
    StagingStore(db).upsert_row(
        {
            "igdb_id": 9,
            "name": "Human Game",
            "match_status": "new_candidate",
            "source": "popular",
            "staging_status": "pending_review",
        }
    )
    appr = ApprovalStore(db, lane=LANE_STAGING)
    appr.decide(9, "approve", actor="local_reviewer", note="real human")
    bad = appr.revoke_simulation_approval(9, note="should fail")
    assert not bad["ok"]
    assert bad["error"] == "refuse_revoke_human_approval"


def test_five_nights_legacy_high_without_demand():
    audit = audit_five_nights_style_legacy(
        metric_norm=1.0,
        steam_verified=True,
        in_quenly=False,
        is_free=False,
        category="new_releases",
        steam_recommendations=None,
        review_bucket="APPROVABLE",
    )
    assert audit["explained_total"] >= 90
    scored = ScoredCandidate(
        candidate=IgdbCandidate(
            igdb_id=405935,
            name="Five Nights with Maids",
            slug=None,
            game_type=0,
            first_release_date=None,
            steam_appid=4771580,
            source="new_releases",
        ),
        category="new_releases",
        metric_name="visits",
        metric_raw=0.001,
        metric_norm=1.0,
    )
    tri = compute_tri_score(
        scored,
        in_quenly=False,
        is_free=False,
        steam_resolution_status="verified",
        steam_verified=True,
        review_bucket="APPROVABLE",
        steam_recommendations=None,
        store_coverage_status="unknown",
        release_status="released",
        legacy_total=98.0,
    )
    # PopScore alone can yield demand score, but commercial stays unknown.
    assert tri.commercial.score is None
    assert "store_coverage_unknown_not_absence" in tri.commercial.missing_signals


def test_store_coverage_sample_labels(tmp_path: Path):
    cands = [
        {
            "igdb_id": 1,
            "name": "A",
            "steam_appid": None,
            "in_quenly": False,
            "steam_resolution": {"status": "verified"},
        },
        {
            "igdb_id": 2,
            "name": "B",
            "steam_appid": None,
            "in_quenly": True,
            "steam_resolution": {"status": "verified"},
        },
    ]
    out = analyze_candidates(
        cands,
        index=__import__(
            "tools.igdb_discovery.store_coverage", fromlist=["LocalStoreIndex"]
        ).LocalStoreIndex(catalog_db=tmp_path / "x.db", feeds_dir=tmp_path),
        run_id="test_run",
        sample="unit",
    )
    assert out["run_id"] == "test_run"
    assert "batch_all" in out["sample_definitions"]
    assert "verified_new_only" in out["sample_definitions"]
    assert out["sample_definitions"]["batch_all"]["n"] == 2
    assert out["sample_definitions"]["verified_new_only"]["n"] == 1
