"""Offline enrichment performance measurements (local only)."""
from __future__ import annotations

import json
import time
import tracemalloc
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import config
from .import_queue import assign_all
from .scoring_v5 import compute_tri_score, audit_five_nights_style_legacy
from .store_coverage import LocalStoreIndex, analyze_candidates
from .popularity import ScoredCandidate
from .fetchers import IgdbCandidate


def _tri_for_row(row: dict[str, Any]) -> dict[str, Any]:
    pop = row.get("popularity") or {}
    steam = row.get("steam") or {}
    reso = row.get("steam_resolution") or {}
    rev = row.get("review") or {}
    cov = row.get("store_coverage") or {}
    cand = IgdbCandidate(
        igdb_id=int(row["igdb_id"]),
        name=str(row["name"]),
        slug=row.get("slug"),
        game_type=row.get("game_type"),
        first_release_date=row.get("first_release_date"),
        steam_appid=row.get("steam_appid"),
        source=pop.get("category") or "unknown",
    )
    scored = ScoredCandidate(
        candidate=cand,
        category=pop.get("category") or "unknown",
        metric_name=pop.get("metric_name") or "unknown",
        metric_raw=pop.get("metric_raw"),
        metric_norm=pop.get("metric_norm"),
        trending_insufficient_history=bool(pop.get("trending_insufficient_history")),
    )
    return compute_tri_score(
        scored,
        in_quenly=bool(row.get("in_quenly")),
        is_free=steam.get("is_free"),
        steam_resolution_status=reso.get("status"),
        steam_verified=bool(rev.get("steam_verified")),
        review_bucket=rev.get("bucket") or "NEEDS_REVIEW",
        steam_recommendations=steam.get("recommendations"),
        store_coverage_status=cov.get("status"),
        release_status="upcoming" if steam.get("coming_soon") else "released",
        trending_insufficient_history=bool(pop.get("trending_insufficient_history")),
        legacy_total=rev.get("scan_priority"),
    ).to_dict()


def bench_sizes(sizes: list[int] | None = None) -> dict[str, Any]:
    sizes = sizes or [100, 250, 500]
    latest = config.REPORTS_DIR / "discovery_latest.json"
    base = json.loads(latest.read_text(encoding="utf-8")).get("candidates") or []
    if not base:
        return {"ok": False, "error": "no_candidates"}

    # Expand by cycling if needed (offline stress only — same objects).
    pool = list(base)
    while len(pool) < max(sizes):
        pool.extend(deepcopy(base))

    idx = LocalStoreIndex()
    t_cache0 = time.perf_counter()
    meta = idx.load()
    cache_load_sec = time.perf_counter() - t_cache0

    results = []
    for n in sizes:
        sample = deepcopy(pool[:n])
        tracemalloc.start()
        t0 = time.perf_counter()
        cov = analyze_candidates(
            sample, index=idx, run_id=f"perf_{n}", sample=f"perf_batch_{n}"
        )
        t_cov = time.perf_counter() - t0
        t1 = time.perf_counter()
        for row in sample:
            by = {int(r["igdb_id"]): r for r in cov["results"]}
            row["store_coverage"] = by.get(int(row["igdb_id"]), {"status": "unknown"})
            row["tri_score"] = _tri_for_row(row)
        assign_all(sample)
        t_score = time.perf_counter() - t1
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        results.append(
            {
                "n": n,
                "coverage_sec": round(t_cov, 3),
                "tri_score_and_queue_sec": round(t_score, 3),
                "total_sec": round(t_cov + t_score, 3),
                "peak_memory_mb": round(peak / (1024 * 1024), 2),
                "steam_appdetails_calls": 0,
                "note": "offline — no Steam/IGDB HTTP",
            }
        )

    # Five Nights audit
    fn = next((c for c in base if c.get("igdb_id") == 405935), None)
    fn_audit = None
    if fn:
        pop = fn.get("popularity") or {}
        steam = fn.get("steam") or {}
        rev = fn.get("review") or {}
        fn_audit = {
            "name": fn.get("name"),
            "legacy_priority": rev.get("scan_priority"),
            "legacy_breakdown": audit_five_nights_style_legacy(
                metric_norm=pop.get("metric_norm"),
                steam_verified=True,
                in_quenly=False,
                is_free=steam.get("is_free"),
                category=pop.get("category") or "new_releases",
                steam_recommendations=steam.get("recommendations"),
                review_bucket=rev.get("bucket") or "APPROVABLE",
            ),
            "tri_score": _tri_for_row(
                {
                    **fn,
                    "store_coverage": fn.get("store_coverage") or {"status": "unknown"},
                }
            ),
        }

    out = {
        "cache_load_sec": round(cache_load_sec, 3),
        "feed_meta": meta.get("feed_row_counts"),
        "offers_count": meta.get("local_offers_count"),
        "sizes": results,
        "five_nights_with_maids_audit": fn_audit,
        "v4_offline_enrich_was_sec": 46.893,
        "optimization_note": (
            "V4 46.8s was full CSV scan per candidate; V5 uses token index only."
        ),
    }
    (config.REPORTS_DIR / "perf_bench_latest.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out
