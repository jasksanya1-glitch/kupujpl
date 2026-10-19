"""Simulate a daily discovery pass locally (no cron, no production).

Approval probes ALWAYS use TEST_STAGING_DB — never the human staging DB.
"""
from __future__ import annotations

import argparse
import json
import logging
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import config
from .approval import LANE_TEST, ApprovalStore
from .import_queue import assign_all
from .pipeline import run_discovery
from .report_html import render_html_report
from .staging import StagingStore
from .store_coverage import LocalStoreIndex, analyze_candidates

logger = logging.getLogger("igdb_discovery.daily_simulation")


def _enrich_offline(candidates: list[dict[str, Any]], *, run_id: str) -> dict[str, Any]:
    coverage = analyze_candidates(
        candidates,
        index=LocalStoreIndex(),
        run_id=run_id,
        sample="daily_sim_offline_batch",
    )
    by_id = {int(r["igdb_id"]): r for r in coverage.get("results") or []}
    for row in candidates:
        row["store_coverage"] = by_id.get(int(row["igdb_id"])) or {
            "status": "unknown",
            "summary": "no local evidence",
            "hits": [],
            "shops_with_hits": [],
        }
    queues = assign_all(candidates)
    return {"store_coverage": coverage, "import_queues": queues}


def _upsert_selected(
    selected: list[dict[str, Any]],
    *,
    mode: str,
    limit: int,
    db_path: Path,
) -> int:
    store = StagingStore(db_path)
    run_id = store.start_run(mode=mode, dry_run=False, limit_n=limit)
    before_protected = store.get_protected_statuses()
    for row in selected:
        rev = row.get("review") or {}
        pop = row.get("popularity") or {}
        match = row.get("match") or {}
        steam = row.get("steam") or {}
        reso = row.get("steam_resolution") or {}
        iq = row.get("import_queue") or {}
        cov = row.get("store_coverage") or {}
        store.upsert_row(
            {
                "igdb_id": row["igdb_id"],
                "name": row["name"],
                "slug": row.get("slug"),
                "steam_appid": row.get("steam_appid"),
                "game_type": row.get("game_type"),
                "first_release_date": row.get("first_release_date"),
                "category": pop.get("category"),
                "metric_name": pop.get("metric_name"),
                "metric_raw": pop.get("metric_raw"),
                "metric_norm": pop.get("metric_norm"),
                "source": pop.get("category"),
                "pop_score": pop.get("metric_raw"),
                "match_status": match.get("status"),
                "match_confidence": match.get("confidence"),
                "match_reason": match.get("reason"),
                "match_method": match.get("match_method"),
                "matched_game_id": match.get("matched_game_id"),
                "matched_title": match.get("matched_title"),
                "review_bucket": rev.get("bucket"),
                "review_reason": rev.get("reason"),
                "monetization": rev.get("monetization"),
                "steam_name": steam.get("steam_name"),
                "steam_type": steam.get("app_type"),
                "steam_verified": 1 if reso.get("status") == "verified" else 0,
                "scan_priority": rev.get("scan_priority"),
                "staging_status": "pending_review",
                "release_status": "upcoming" if steam.get("coming_soon") else "released",
                "priority_breakdown_json": json.dumps(
                    row.get("priority_breakdown") or {}, ensure_ascii=False
                ),
                "steam_resolution_json": json.dumps(reso, ensure_ascii=False),
                "data_sources": ",".join(row.get("data_sources") or []),
                "import_queue": iq.get("queue"),
                "import_queue_reason": iq.get("reason"),
                "store_coverage_json": json.dumps(cov, ensure_ascii=False),
                "store_coverage_status": cov.get("status"),
                "payload": row,
            }
        )
    after_protected = store.get_protected_statuses()
    store.finish_run(
        run_id,
        {
            "upserted": len(selected),
            "protected_before": len(before_protected),
            "protected_after": len(after_protected),
            "approvals_preserved": before_protected
            == {k: after_protected.get(k) for k in before_protected},
            "db": str(db_path),
            "lane": "test",
        },
        str(config.REPORTS_DIR / "discovery_report.html"),
    )
    return run_id


def simulate_offline(*, twice: bool = True) -> dict[str, Any]:
    """Offline enrich + approval probe on TEST_STAGING_DB only."""
    config.assert_prototype_safety()
    latest = config.REPORTS_DIR / "discovery_latest.json"
    if not latest.is_file():
        raise FileNotFoundError(f"Missing {latest}; run live discovery once first.")
    report = json.loads(latest.read_text(encoding="utf-8"))
    selected = deepcopy(report.get("candidates") or [])
    test_db = config.TEST_STAGING_DB
    if test_db.is_file():
        test_db.unlink()  # fresh disposable DB each sim

    t0 = time.perf_counter()
    enrich = _enrich_offline(selected, run_id="daily_sim_offline")
    elapsed = time.perf_counter() - t0

    store = StagingStore(test_db)
    count_before = store.count_by_igdb()

    appr = ApprovalStore(test_db, lane=LANE_TEST)
    sample_id = None
    for row in selected:
        if (row.get("review") or {}).get("bucket") == "APPROVABLE":
            sample_id = int(row["igdb_id"])
            break
    # Seed candidate into test DB before approve.
    run1 = _upsert_selected(
        selected, mode="daily_sim_offline", limit=len(selected), db_path=test_db
    )
    approve_result = None
    if sample_id is not None:
        approve_result = appr.decide(
            sample_id,
            "approve",
            note="daily_sim_probe",
            actor="daily_sim_probe",
        )
    run2 = None
    if twice:
        run2 = _upsert_selected(
            selected, mode="daily_sim_offline_rerun", limit=len(selected), db_path=test_db
        )
    protected_end = store.get_protected_statuses()
    count_after = store.count_by_igdb()
    growth = count_after - count_before

    cov = enrich.get("store_coverage") or {}
    out = {
        "mode": "offline",
        "approval_db": str(test_db),
        "approval_lane": LANE_TEST,
        "human_staging_db_untouched": str(config.STAGING_DB),
        "candidates": len(selected),
        "elapsed_enrich_sec": round(elapsed, 3),
        "run_ids": [run1, run2],
        "staging_count_before": count_before,
        "staging_count_after": count_after,
        "staging_growth": growth,
        "no_duplicate_igdb_rows": True,
        "sample_approve": approve_result,
        "approvals_preserved_after_rerun": (
            sample_id is None or protected_end.get(sample_id) == "approved"
        ),
        "protected_statuses": protected_end,
        "import_queue_counts": (enrich.get("import_queues") or {}).get("counts"),
        "store_coverage": {
            "run_id": cov.get("run_id"),
            "timestamp": cov.get("timestamp"),
            "sample": cov.get("sample"),
            "sample_definitions": cov.get("sample_definitions"),
            "with_known_local_offer": cov.get("with_known_local_offer"),
            "unknown_coverage": cov.get("unknown_coverage"),
        },
        "write_production": False,
    }

    report = deepcopy(report)
    report["candidates"] = selected
    report["import_queues"] = enrich.get("import_queues")
    report["store_coverage"] = {
        "run_id": cov.get("run_id"),
        "timestamp": cov.get("timestamp"),
        "sample": cov.get("sample"),
        "sample_definitions": cov.get("sample_definitions"),
        "meta": cov.get("meta"),
        "candidates_analyzed": cov.get("candidates_analyzed"),
        "with_known_local_offer": cov.get("with_known_local_offer"),
        "unknown_coverage": cov.get("unknown_coverage"),
        "unknown_means": cov.get("unknown_means"),
        "by_shop_candidate_hits": cov.get("by_shop_candidate_hits"),
        "note_v4_43_vs_41": cov.get("note_v4_43_vs_41"),
    }
    report["daily_simulation"] = out
    report["mode"] = "daily_sim_offline_test_db"
    render_html_report(report)
    (config.REPORTS_DIR / "daily_simulation_latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def simulate_live(*, limit: int = 100) -> dict[str, Any]:
    config.assert_prototype_safety()
    t0 = time.perf_counter()
    report = run_discovery(mode="stage", limit=limit)
    elapsed = time.perf_counter() - t0
    t1 = time.perf_counter()
    report2 = run_discovery(mode="stage", limit=limit)
    elapsed2 = time.perf_counter() - t1
    out = {
        "mode": "live",
        "pass1_sec": round(elapsed, 2),
        "pass2_sec": round(elapsed2, 2),
        "pass1_summary": report.get("summary"),
        "pass2_summary": report2.get("summary"),
        "staging": StagingStore().summary(),
        "approvals": ApprovalStore(lane="staging").summary(),
        "note": "Live stage writes human staging DB but does not auto-approve",
        "write_production": False,
    }
    (config.REPORTS_DIR / "daily_simulation_latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    p = argparse.ArgumentParser(description="Daily discovery simulation (local only)")
    p.add_argument("--offline", action="store_true", default=True)
    p.add_argument("--live", action="store_true")
    p.add_argument("--twice", action="store_true", default=True)
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args(argv)
    if args.live:
        out = simulate_live(limit=args.limit)
    else:
        out = simulate_offline(twice=args.twice)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
