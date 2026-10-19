"""Re-apply V4 classify + queues + coverage on discovery_latest without network."""
from __future__ import annotations

import json
from pathlib import Path

from . import config
from .classify import classify
from .fetchers import IgdbCandidate
from .import_queue import assign_all
from .matching import MatchResult
from .report_html import render_html_report
from .steam_verify import SteamCheck
from .store_coverage import LocalStoreIndex, analyze_candidates
from .write_v4_report import build as build_v4


def _steam_from_dict(d: dict) -> SteamCheck:
    return SteamCheck(
        steam_appid=int(d["steam_appid"]) if d.get("steam_appid") else 0,
        available=bool(d.get("available")),
        unverified=bool(d.get("unverified")),
        steam_name=d.get("steam_name"),
        app_type=d.get("app_type"),
        title_ok=d.get("title_ok"),
        title_reason=d.get("title_reason"),
        windows=d.get("windows"),
        is_free=d.get("is_free"),
        coming_soon=bool(d.get("coming_soon")),
        release_date=d.get("release_date"),
        recommendations=d.get("recommendations"),
        error=d.get("error"),
    )


def main() -> None:
    path = config.REPORTS_DIR / "discovery_latest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    cands = data.get("candidates") or []

    for row in cands:
        cand = IgdbCandidate(
            igdb_id=int(row["igdb_id"]),
            name=str(row["name"]),
            slug=row.get("slug"),
            game_type=row.get("game_type"),
            first_release_date=row.get("first_release_date"),
            steam_appid=row.get("steam_appid"),
            source=(row.get("popularity") or {}).get("category") or "unknown",
        )
        m = row.get("match") or {}
        match = MatchResult(
            status=m.get("status") or "new_candidate",
            confidence=float(m.get("confidence") or 0),
            reason=m.get("reason") or "",
            matched_game_id=m.get("matched_game_id"),
            matched_title=m.get("matched_title"),
            matched_steam_appid=m.get("matched_steam_appid"),
            match_method=m.get("match_method"),
        )
        steam = _steam_from_dict(row.get("steam") or {})
        pop = row.get("popularity") or {}
        reso = row.get("steam_resolution") or {}
        verdict = classify(
            cand,
            match,
            steam,
            category=pop.get("category"),
            metric_norm=pop.get("metric_norm"),
            steam_resolution_status=reso.get("status"),
        )
        # Keep prior scan_priority if present.
        prior = (row.get("review") or {}).get("scan_priority")
        if prior is not None:
            verdict.scan_priority = float(prior)
        row["review"] = verdict.to_dict()

    cov = analyze_candidates(cands, index=LocalStoreIndex())
    by_id = {int(r["igdb_id"]): r for r in cov.get("results") or []}
    for row in cands:
        row["store_coverage"] = by_id.get(int(row["igdb_id"])) or {"status": "unknown"}
    queues = assign_all(cands)

    from collections import Counter

    data["candidates"] = cands
    data["import_queues"] = queues
    data["store_coverage"] = {
        "meta": cov.get("meta"),
        "candidates_analyzed": cov.get("candidates_analyzed"),
        "with_known_local_offer": cov.get("with_known_local_offer"),
        "unknown_coverage": cov.get("unknown_coverage"),
        "unknown_means": cov.get("unknown_means"),
        "by_shop_candidate_hits": cov.get("by_shop_candidate_hits"),
    }
    data["bucket_counts"] = dict(
        Counter((r.get("review") or {}).get("bucket") for r in cands)
    )
    data["summary"] = data.get("summary") or {}
    data["summary"]["approvable"] = data["bucket_counts"].get("APPROVABLE", 0)
    data["summary"]["needs_review"] = data["bucket_counts"].get("NEEDS_REVIEW", 0)
    data["mode"] = "v4_reclassify_offline"
    data["go_nogo"] = {
        "verdict": "CONDITIONAL GO — V4 staging + approval ready; no production import",
        "detail": (
            "Offline reclassify with V4 demand-signal honesty + store coverage + queues. "
            "Production untouched."
        ),
    }

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    render_html_report(data)
    v4 = build_v4()
    print("buckets", data["bucket_counts"])
    print("queues", queues.get("counts"))
    print("store", cov.get("with_known_local_offer"), cov.get("unknown_coverage"))
    print("v4", v4)


if __name__ == "__main__":
    main()
