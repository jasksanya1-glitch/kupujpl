"""Game Discovery V5 offline orchestration (local prototype only)."""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config
from .daily_simulation import simulate_offline
from .fetchers import IgdbCandidate
from .import_queue import QUEUE_HIGH, assign_all
from .perf_bench import bench_sizes, _tri_for_row
from .popularity import ScoredCandidate
from .rankings import build_rankings_offline_from_discovery
from .rankings_report import render_rankings_html
from .report_html import render_html_report
from .scoring_v5 import assign_queue_v5, audit_five_nights_style_legacy, compute_tri_score
from .steam_istore import credential_report, istore_has_appid
from .store_coverage import LocalStoreIndex, analyze_candidates

logger = logging.getLogger("igdb_discovery.run_v5")


def _apply_tri_and_queues(cands: list[dict[str, Any]]) -> None:
    for row in cands:
        row["tri_score"] = _tri_for_row(row)
        row["import_queue"] = assign_queue_v5(row)


def run_v5_offline() -> dict[str, Any]:
    config.assert_prototype_safety()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    latest = config.REPORTS_DIR / "discovery_latest.json"
    data = json.loads(latest.read_text(encoding="utf-8"))
    cands = data.get("candidates") or []

    # Store coverage with explicit sample labeling
    cov = analyze_candidates(
        cands,
        index=LocalStoreIndex(),
        run_id="v5_offline_cov",
        sample="discovery_latest_all_candidates",
    )
    by_id = {int(r["igdb_id"]): r for r in cov["results"]}
    for row in cands:
        row["store_coverage"] = by_id.get(int(row["igdb_id"]), {"status": "unknown"})

    _apply_tri_and_queues(cands)
    v5_queue_counts = Counter(
        (c.get("import_queue") or {}).get("queue") for c in cands
    )

    # IStore enrichment status (no forced key request)
    istore = credential_report().to_dict()
    istore_hits = {"checked": 0, "in_cache": 0, "unknown_cache": 0, "not_in_cache": 0}
    for row in cands:
        appid = row.get("steam_appid")
        if not appid:
            row["istore"] = {"status": "unknown", "reason": "no_steam_appid"}
            continue
        istore_hits["checked"] += 1
        present = istore_has_appid(int(appid))
        if present is None:
            istore_hits["unknown_cache"] += 1
            row["istore"] = {"status": "unknown", "reason": "cache_or_key_unavailable"}
        elif present:
            istore_hits["in_cache"] += 1
            row["istore"] = {"status": "present", "reason": "istore_cache_hit"}
        else:
            istore_hits["not_in_cache"] += 1
            row["istore"] = {"status": "absent_from_cache", "reason": "not_in_local_istore"}

    rankings = build_rankings_offline_from_discovery(top_n=100)
    rankings_html = render_rankings_html(rankings)

    perf = bench_sizes([100, 250, 500])
    sim = simulate_offline(twice=True)

    verified_new = [
        c
        for c in cands
        if not c.get("in_quenly")
        and (c.get("steam_resolution") or {}).get("status") == "verified"
    ]
    recommended = [
        c
        for c in verified_new
        if (c.get("import_queue") or {}).get("queue") == QUEUE_HIGH
        or (
            (c.get("review") or {}).get("bucket") == "APPROVABLE"
            and (c.get("tri_score") or {}).get("high_priority_eligible")
        )
    ]
    # Top 20 missing by confirmed demand score
    missing = [c for c in cands if not c.get("in_quenly")]
    top20 = sorted(
        missing,
        key=lambda r: (
            0 if ((r.get("tri_score") or {}).get("demand") or {}).get("score") is not None else 1,
            -float((((r.get("tri_score") or {}).get("demand") or {}).get("score") or 0)),
            -float((((r.get("tri_score") or {}).get("identity") or {}).get("score") or 0)),
        ),
    )[:20]

    popular_list = (rankings.get("lists") or {}).get("POPULAR") or []
    new_list = (rankings.get("lists") or {}).get("NEW_RELEASES") or []
    up_list = (rankings.get("lists") or {}).get("UPCOMING") or []

    vn_sample = cov["sample_definitions"]["verified_new_only"]
    batch_sample = cov["sample_definitions"]["batch_all"]

    go = {
        "discovery_staging": {
            "verdict": "CONDITIONAL GO",
            "detail": "Staging upsert + Steam resolve + queues ready; commercial IGDB still required for VPS.",
        },
        "rankings_staging": {
            "verdict": "CONDITIONAL GO",
            "detail": "Local rankings dashboard built; insufficient_history flagged for trending when needed.",
        },
        "approval_workflow": {
            "verdict": "GO",
            "detail": "Sim approve revoked; test lane isolated; loopback POST-only mutations.",
        },
        "production_import": {
            "verdict": "NO-GO",
            "detail": "No automatic import; commercial IGDB OK required.",
        },
        "production_publishing": {
            "verdict": "NO-GO",
            "detail": "Approve never publishes; production DB untouched.",
        },
    }

    report = {
        "version": 5,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": cands,
        "store_coverage": cov,
        "rankings": {
            "run_id": rankings.get("run_id"),
            "counts": rankings.get("counts"),
            "popular_in_quenly": rankings.get("popular_in_quenly"),
            "popular_missing": rankings.get("popular_missing"),
            "html": str(rankings_html),
        },
        "steam_istore": {**istore, "hits": istore_hits},
        "perf": perf,
        "daily_simulation": sim,
        "v5_queue_counts": dict(v5_queue_counts),
        "summary": {
            "analyzed": len(cands),
            "catalog_games": (data.get("summary") or {}).get("catalog_games"),
            "popular_in_quenly": rankings.get("popular_in_quenly"),
            "popular_missing": rankings.get("popular_missing"),
            "new_releases_listed": len(new_list),
            "upcoming_listed": len(up_list),
            "verified_new": len(verified_new),
            "high_priority_recommended": len(recommended),
            "store_batch": batch_sample,
            "store_verified_new": vn_sample,
            "steam_match_verified": sum(
                1
                for c in cands
                if (c.get("steam_resolution") or {}).get("status") == "verified"
            ),
            "steam_match_ambiguous": sum(
                1
                for c in cands
                if (c.get("steam_resolution") or {}).get("status") == "ambiguous_manual_review"
            ),
        },
        "top20_missing_by_demand": [
            {
                "name": c.get("name"),
                "igdb_id": c.get("igdb_id"),
                "steam_appid": c.get("steam_appid"),
                "demand": (c.get("tri_score") or {}).get("demand"),
                "identity": (c.get("tri_score") or {}).get("identity"),
                "commercial": (c.get("tri_score") or {}).get("commercial"),
                "high_priority": (c.get("tri_score") or {}).get("high_priority_eligible"),
                "high_priority_reason": (c.get("tri_score") or {}).get("high_priority_reason"),
                "queue": (c.get("import_queue") or {}).get("queue"),
                "store": (c.get("store_coverage") or {}).get("status"),
            }
            for c in top20
        ],
        "recommended": [
            {
                "name": c.get("name"),
                "igdb_id": c.get("igdb_id"),
                "reason": (c.get("tri_score") or {}).get("high_priority_reason"),
                "demand": (c.get("tri_score") or {}).get("demand"),
            }
            for c in recommended
        ],
        "go_nogo": go,
        "safety": {
            "production_db": False,
            "scanners": False,
            "cron": False,
            "auto_import": False,
            "auto_publish": False,
            "design": False,
            "price_engine_v2": False,
        },
    }

    # Refresh discovery HTML with tri-score context
    data["candidates"] = cands
    data["store_coverage"] = {
        "run_id": cov.get("run_id"),
        "timestamp": cov.get("timestamp"),
        "sample": cov.get("sample"),
        "sample_definitions": cov.get("sample_definitions"),
        "with_known_local_offer": cov.get("with_known_local_offer"),
        "unknown_coverage": cov.get("unknown_coverage"),
        "unknown_means": cov.get("unknown_means"),
        "by_shop_candidate_hits": cov.get("by_shop_candidate_hits"),
        "note_v4_43_vs_41": cov.get("note_v4_43_vs_41"),
    }
    data["v5"] = {"go_nogo": go, "summary": report["summary"]}
    render_html_report(data)

    _write_markdown(report)
    out_json = config.REPORTS_DIR / "DISCOVERY_V5_REPORT.json"
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (config.REPORTS_DIR / "discovery_latest.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def _write_markdown(report: dict[str, Any]) -> Path:
    s = report["summary"]
    go = report["go_nogo"]
    lines = [
        "# Game Discovery V5 Report",
        "",
        f"**Generated:** {report['generated_at']}",
        "",
        "## GO / NO-GO",
        "",
    ]
    for k, v in go.items():
        lines.append(f"- **{k}:** {v['verdict']} — {v['detail']}")
    lines += [
        "",
        "## Required answers",
        "",
        f"1. Popular already in Quenly (ranking sample): **{s.get('popular_in_quenly')}**",
        f"2. Popular missing: **{s.get('popular_missing')}**",
        f"3. New releases listed (actual, not padded): **{s.get('new_releases_listed')}**",
        f"4. Upcoming confirmed listed: **{s.get('upcoming_listed')}**",
        f"5. HIGH_PRIORITY recommended: **{s.get('high_priority_recommended')}**",
        "6. Top-20 missing by confirmed demand — see JSON `top20_missing_by_demand`",
        f"7. Store coverage batch: `{s.get('store_batch')}`",
        f"   Store coverage verified-new: `{s.get('store_verified_new')}`",
        "8. High priority only when demand+identity pass V5 gate (not legacy 98 novelty stack)",
        f"9. Steam matching verified={s.get('steam_match_verified')} ambiguous={s.get('steam_match_ambiguous')}",
        "10. Ready for Quenly lists? **CONDITIONAL GO** for local rankings/discovery staging; **NO-GO** production import/publish",
        "",
        "## Five Nights with Maids legacy audit",
        "",
        "```",
        json.dumps(
            (report.get("perf") or {}).get("five_nights_with_maids_audit"),
            ensure_ascii=False,
            indent=2,
        )[:2000],
        "```",
        "",
        "## Perf",
        "",
        f"`{(report.get('perf') or {}).get('sizes')}`",
        "",
        f"Cache load: {(report.get('perf') or {}).get('cache_load_sec')}s",
        "",
        "## Safety",
        "",
        f"`{report.get('safety')}`",
        "",
    ]
    path = config.REPORTS_DIR / "DISCOVERY_V5_GO_NOGO.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rep = run_v5_offline()
    print(json.dumps({"go_nogo": rep["go_nogo"], "summary": rep["summary"]}, indent=2))
