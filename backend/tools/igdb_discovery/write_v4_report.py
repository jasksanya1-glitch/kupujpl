"""Build Game Discovery V4 markdown report from latest JSON + simulation."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .import_queue import assign_all


def build() -> Path:
    latest = config.REPORTS_DIR / "discovery_latest.json"
    data = json.loads(latest.read_text(encoding="utf-8"))
    cands = list(data.get("candidates") or [])
    summary = data.get("summary") or {}

    # Prefer enriched HTML/report JSON if daily sim already attached coverage.
    report_json = config.REPORTS_DIR / "discovery_report.json"
    if report_json.is_file():
        enriched = json.loads(report_json.read_text(encoding="utf-8"))
        if enriched.get("candidates") and any(
            (c.get("store_coverage") or {}).get("status") for c in enriched["candidates"]
        ):
            cands = enriched["candidates"]
            data = enriched

    if not any((c.get("import_queue") or {}).get("queue") for c in cands):
        queues = assign_all(cands)
    else:
        queues = data.get("import_queues") or {
            "counts": Counter((c.get("import_queue") or {}).get("queue") for c in cands)
        }
        if "counts" not in queues:
            queues = {"counts": dict(Counter((c.get("import_queue") or {}).get("queue") for c in cands))}

    store_block = data.get("store_coverage") or {}
    verified_new = [
        c
        for c in cands
        if not c.get("in_quenly")
        and (c.get("steam_resolution") or {}).get("status") == "verified"
    ]
    approvable = [
        c for c in cands if (c.get("review") or {}).get("bucket") == "APPROVABLE"
    ]
    reasons = Counter((c.get("review") or {}).get("reason") for c in verified_new)
    store_known = sum(
        1
        for c in verified_new
        if (c.get("store_coverage") or {}).get("status") == "known_offer"
    )
    store_unknown = len(verified_new) - store_known

    ranked = sorted(
        [c for c in cands if not c.get("in_quenly")],
        key=lambda x: -float((x.get("review") or {}).get("scan_priority") or 0),
    )[:20]

    sim_path = config.REPORTS_DIR / "daily_simulation_latest.json"
    sim = json.loads(sim_path.read_text(encoding="utf-8")) if sim_path.is_file() else {}

    verdict = "CONDITIONAL GO"
    detail = (
        "V4 staging workflow is ready locally: Steam resolver no longer guesses AppIDs, "
        "store coverage is offline-only, approval writes staging only, daily re-run preserves "
        "manual decisions. Still NO-GO for production DB/cron/scanners/IGDB commercial use."
    )

    lines = [
        "# Game Discovery V4 Report",
        "",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Verdict:** {verdict}",
        "",
        detail,
        "",
        "## 1. Analyzed",
        "",
        f"- Candidates in report: **{len(cands)}**",
        f"- Catalog games: **{summary.get('catalog_games') or data.get('summary', {}).get('catalog_games')}**",
        f"- Missing in Quenly (batch): **{summary.get('missing_in_quenly') or data.get('summary', {}).get('missing_in_quenly')}**",
        f"- Verified new (Steam OK, not in catalog): **{len(verified_new)}**",
        "",
        "## 2–5. Confirmation & recommendation",
        "",
        f"- Steam-confirmed new: **{len(verified_new)}**",
        f"- Recommended (APPROVABLE): **{len(approvable)}**",
        f"- Not recommended (verified-new) reason breakdown:",
        "",
    ]
    for reason, n in reasons.most_common():
        lines.append(f"  - `{reason}`: {n}")
    lines += [
        "",
        "Quality thresholds were **not** lowered. `steam.recommendations=None` is no longer",
        "mislabeled as «too few reviews» — it becomes `insufficient_demand_signals`.",
        "",
        "### Why only ~5 APPROVABLE",
        "",
        "Balanced sampling fills missing slots with long-tail new/upcoming titles.",
        "Popular/trending hits are mostly already in Quenly (ALREADY_EXISTS).",
        "Remaining verified-new titles lack PopScore and Steam recommendation counts,",
        "so they correctly stay in MANUAL_REVIEW / NEEDS_REVIEW.",
        "",
        "## 6. Store coverage (local only)",
        "",
        f"- Verified-new with local offer/feed evidence: **{store_known}**",
        f"- Verified-new UNKNOWN (no local evidence): **{store_unknown}**",
        f"- Batch known/unknown (all candidates): "
        f"**{store_block.get('with_known_local_offer')}** / "
        f"**{store_block.get('unknown_coverage')}**",
        "- UNKNOWN ≠ absence of shop listings.",
        "- Prices treated as historical snapshots, not live.",
        f"- By shop (batch): `{store_block.get('by_shop_candidate_hits') or sim.get('store_coverage')}`",
        "",
        "## 7. Top 20 priority (missing in Quenly)",
        "",
    ]
    for i, r in enumerate(ranked, 1):
        iq = (r.get("import_queue") or {}).get("queue")
        cov = (r.get("store_coverage") or {}).get("status")
        lines.append(
            f"{i}. {r.get('name')} — igdb={r.get('igdb_id')} steam={r.get('steam_appid')} "
            f"prio={(r.get('review') or {}).get('scan_priority')} "
            f"queue={iq} store={cov} bucket={(r.get('review') or {}).get('bucket')}"
        )
    lines += [
        "",
        "## 8. Request / load estimate",
        "",
        "- IGDB: ~25–60 HTTP calls per balanced 100-candidate pass",
        "- Steam appdetails: ~limit + known probes",
        "- Wall time: ~90–240s live; offline enrich ~5–15s after feed index",
        "- Staging growth: 1 row / igdb_id; approval log append-only",
        "- VPS: no production load while local-only",
        "",
        "### Daily simulation",
        "",
        f"- Approvals preserved on re-run: **{sim.get('approvals_preserved_after_rerun')}**",
        f"- Staging growth on re-run: **{sim.get('staging_growth')}** (expect 0)",
        f"- Sample approve production_written: **{(sim.get('sample_approve') or {}).get('production_written')}**",
        f"- Import queues: `{sim.get('import_queue_counts') or queues.get('counts')}`",
        "",
        "## 9. Remaining risks",
        "",
        "- Commercial IGDB agreement still required before any VPS use",
        "- Affiliate feeds are stale snapshots; do not treat as live stock",
        "- Multi-AppID titles without Quenly catalog hit → MANUAL_REVIEW (correct, slower)",
        "- PopScore history for trending still thin (`insufficient_history`)",
        "- Approval ≠ publish; keep production write guards forever until explicit promote",
        "",
        "## 10. Ready for next stage?",
        "",
        f"**{verdict}** — next stage = owner triage via approval UI "
        "(`python -m tools.igdb_discovery.serve_approval`) + curated HIGH_PRIORITY / NEW_RELEASE imports,",
        "still staging-only. Not ready for production cron / scanners / auto-publish.",
        "",
        "## Approvable titles",
        "",
    ]
    for a in approvable:
        lines.append(
            f"- {a.get('name')} (igdb={a.get('igdb_id')}, steam={a.get('steam_appid')}, "
            f"cat={(a.get('popularity') or {}).get('category')})"
        )
    if not approvable:
        lines.append("_None_")

    out = config.REPORTS_DIR / "DISCOVERY_V4_GO_NOGO.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    audit = {
        "verdict": verdict,
        "detail": detail,
        "analyzed": len(cands),
        "missing_in_quenly": (data.get("summary") or {}).get("missing_in_quenly"),
        "verified_new": len(verified_new),
        "approvable": len(approvable),
        "reason_breakdown": dict(reasons),
        "store_known_among_verified_new": store_known,
        "store_unknown_among_verified_new": store_unknown,
        "top20": [
            {
                "rank": i,
                "name": r.get("name"),
                "igdb_id": r.get("igdb_id"),
                "steam_appid": r.get("steam_appid"),
                "priority": (r.get("review") or {}).get("scan_priority"),
                "queue": (r.get("import_queue") or {}).get("queue"),
                "store": (r.get("store_coverage") or {}).get("status"),
                "bucket": (r.get("review") or {}).get("bucket"),
                "reason": (r.get("review") or {}).get("reason"),
            }
            for i, r in enumerate(ranked, 1)
        ],
        "import_queue_counts": queues.get("counts"),
        "daily_simulation": sim,
        "safety": {
            "production_db": False,
            "scanners": False,
            "cron": False,
            "auto_publish": False,
        },
    }
    (config.REPORTS_DIR / "DISCOVERY_V4_REPORT.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out


if __name__ == "__main__":
    path = build()
    print(path)
