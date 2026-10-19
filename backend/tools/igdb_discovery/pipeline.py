"""IGDB discovery pipeline: verify → categorize → classify → report.

Modes:
  dry-run  — compute everything, write JSON/HTML reports only (no staging DB writes)
  stage    — same + upsert into isolated staging SQLite (never production)
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from . import config
from .classify import (
    BUCKET_ALREADY,
    BUCKET_APPROVABLE,
    BUCKET_F2P,
    BUCKET_NEEDS_REVIEW,
    BUCKET_QUARANTINE,
    BUCKET_REJECTED,
    classify,
)
from .client import IgdbClient
from .import_queue import assign_all
from .matching import CatalogIndex
from .popularity import CATEGORY_NEW, CATEGORY_UPCOMING, collect_categorized
from .report_html import render_html_report
from .scoring import compute_priority_explained
from .steam_istore import credential_report as istore_credential_report
from .steam_resolve import resolve_steam_appid, fetch_steam_external_hits
from .steam_verify import SteamVerifier
from .staging import StagingStore
from .store_coverage import LocalStoreIndex, analyze_candidates

logger = logging.getLogger("igdb_discovery.pipeline")

Mode = Literal["dry-run", "stage"]


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_prior_new_candidates(limit: int = 30) -> list[dict[str, Any]]:
    path = config.REPORTS_DIR / "prototype_latest.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = [
        c
        for c in (data.get("candidates") or [])
        if (c.get("match") or {}).get("status") == "new_candidate"
    ]
    return rows[:limit]


def verify_prior_30(verifier: SteamVerifier, index: CatalogIndex) -> list[dict[str, Any]]:
    """Re-check the 30 new_candidate rows from the first prototype run."""
    from .fetchers import IgdbCandidate
    from .matching import MatchResult

    prior = _load_prior_new_candidates(30)
    out: list[dict[str, Any]] = []
    for row in prior:
        cand = IgdbCandidate(
            igdb_id=int(row["igdb_id"]),
            name=str(row["name"]),
            slug=None,
            game_type=row.get("game_type"),
            first_release_date=None,
            steam_appid=row.get("steam_appid"),
            source=row.get("source") or "prior",
            pop_score=row.get("pop_score"),
        )
        match = index.match(cand)
        steam = verifier.check(cand.steam_appid, cand.name)
        src = cand.source or ""
        cat = {
            "recent": "new_releases",
            "upcoming": "upcoming",
            "popular": "popular",
            "trending": "trending",
            "new_releases": "new_releases",
        }.get(src, "new_releases")
        verdict = classify(cand, match, steam, category=cat, metric_norm=0.0)
        out.append(
            {
                "name": cand.name,
                "igdb_id": cand.igdb_id,
                "steam_appid": cand.steam_appid,
                "steam_name": steam.steam_name,
                "steam_type": steam.app_type,
                "title_ok": steam.title_ok,
                "title_reason": steam.title_reason,
                "monetization": verdict.monetization,
                "pc_release_date": verdict.pc_release_date,
                "bucket": verdict.bucket,
                "reason": verdict.reason,
                "in_quenly": match.status == "already_in_catalog",
                "source": cand.source,
            }
        )
    return out


KNOWN_PROBLEM_GAMES = [
    {"igdb_id": 28512, "name": "Risk of Rain 2", "expect_steam": 632360},
    {"igdb_id": 112874, "name": "Horizon Forbidden West", "expect_steam": None},
    {"igdb_id": 268842, "name": "Horizon Forbidden West: Complete Edition", "expect_steam": 2420110},
    {"igdb_id": 19564, "name": "Death Stranding", "expect_steam": 1190460},
    {"igdb_id": 421963, "name": "The Ramen Bar", "expect_steam": 4940980},
    {"igdb_id": 424328, "name": "Just One More Fly", "expect_steam": 5380190},
    {"igdb_id": 165460, "name": "Your Boyfriend", "expect_steam": 1771650},
]

# RoR2: when AppID is already in Quenly → unique catalog match.
# Without catalog → ambiguous_manual_review (never lowest-AppID guess).
KNOWN_NOTES = {
    28512: "unique_quenly_catalog_steam_or_ambiguous_if_absent",
    112874: "base_sku_no_steam_expected_complete_edition_is_separate_product",
}


def investigate_known_games(
    client: IgdbClient,
    verifier: SteamVerifier,
    index: CatalogIndex,
) -> list[dict[str, Any]]:
    """Regression probe for previously failing titles."""
    ids = [int(g["igdb_id"]) for g in KNOWN_PROBLEM_GAMES]
    hits_map = fetch_steam_external_hits(client, ids)
    out: list[dict[str, Any]] = []
    for spec in KNOWN_PROBLEM_GAMES:
        gid = int(spec["igdb_id"])
        name = str(spec["name"])
        resolution = resolve_steam_appid(
            igdb_game_id=gid,
            igdb_name=name,
            hits=hits_map.get(gid) or [],
            verifier=verifier,
            catalog_steam_ids=set(index.by_steam.keys()),
        )
        expect = spec.get("expect_steam")
        ok = (resolution.appid == expect) if expect is not None else (resolution.appid is None)
        # Horizon base: no steam OK; Complete Edition must resolve 2420110.
        note = KNOWN_NOTES.get(gid, "")
        if gid == 112874 and resolution.status == "none":
            note = KNOWN_NOTES[112874]
            ok = True
        if gid == 28512 and resolution.appid == 632360:
            note = "unique_quenly_catalog_steam_among_verified_candidates"
        elif gid == 28512 and resolution.status == "ambiguous_manual_review":
            note = "multiple_verified_appids_no_catalog_hit_manual_review"
            # Resolver correctly refused to guess; regression still fails expected AppID.
            ok = False
        out.append(
            {
                "name": name,
                "igdb_id": gid,
                "expected_steam": expect,
                "resolved_steam": resolution.appid,
                "resolution": resolution.to_dict(),
                "pass": ok,
                "note": note,
                "in_quenly": resolution.appid in index.by_steam if resolution.appid else False,
            }
        )
    return out


def _process_scored(
    scored_list: list[Any],
    *,
    index: CatalogIndex,
    verifier: SteamVerifier,
    client: IgdbClient,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen_igdb: set[int] = set()
    seen_steam: set[int] = set()

    games = [(s.candidate.igdb_id, s.candidate.name) for s in scored_list]
    hits_map = fetch_steam_external_hits(client, [g for g, _ in games])

    for scored in scored_list:
        cand = scored.candidate
        if cand.igdb_id in seen_igdb:
            continue

        resolution = resolve_steam_appid(
            igdb_game_id=cand.igdb_id,
            igdb_name=cand.name,
            hits=hits_map.get(cand.igdb_id) or [],
            verifier=verifier,
            catalog_steam_ids=set(index.by_steam.keys()),
        )
        cand.steam_appid = resolution.appid

        if cand.steam_appid and cand.steam_appid in seen_steam:
            continue

        category = scored.category
        match = index.match(cand)
        steam = (
            verifier.check(cand.steam_appid, cand.name)
            if cand.steam_appid
            else verifier.check(None, cand.name)
        )

        # Re-file Steam coming_soon out of NEW RELEASES.
        if category == CATEGORY_NEW and steam.coming_soon:
            category = CATEGORY_UPCOMING
            scored.category = CATEGORY_UPCOMING
            scored.notes.append("reclassified_steam_coming_soon_to_upcoming")

        verdict = classify(
            cand,
            match,
            steam,
            category=category,
            metric_norm=scored.metric_norm,
            steam_resolution_status=resolution.status,
        )
        in_quenly = match.status == "already_in_catalog"

        release_status = None
        if steam.coming_soon:
            release_status = "upcoming"
        elif steam.release_date:
            release_status = "released"
        elif cand.first_release_date:
            release_status = "released"
        else:
            release_status = "unknown"

        breakdown = compute_priority_explained(
            scored,
            in_quenly=in_quenly,
            is_free=steam.is_free,
            steam_resolution_status=resolution.status,
            steam_verified=verdict.steam_verified and resolution.status == "verified",
            review_bucket=verdict.bucket,
            steam_recommendations=steam.recommendations,
            release_status=release_status,
            trending_insufficient_history=bool(scored.trending_insufficient_history),
        )
        verdict.scan_priority = breakdown.total

        seen_igdb.add(cand.igdb_id)
        if cand.steam_appid:
            seen_steam.add(cand.steam_appid)

        results.append(
            {
                "igdb_id": cand.igdb_id,
                "name": cand.name,
                "slug": cand.slug,
                "steam_appid": cand.steam_appid,
                "game_type": cand.game_type,
                "first_release_date": cand.first_release_date,
                "version_parent": cand.version_parent,
                "parent_game": cand.parent_game,
                "in_quenly": in_quenly,
                "popularity": {
                    "category": category,
                    "metric_name": scored.metric_name,
                    "metric_raw": scored.metric_raw,
                    "metric_norm": scored.metric_norm,
                    "trending_d7": scored.trending_d7,
                    "trending_d30": scored.trending_d30,
                    "trending_insufficient_history": scored.trending_insufficient_history,
                },
                "match": match.to_dict(),
                "steam": steam.to_dict(),
                "steam_resolution": resolution.to_dict(),
                "priority_breakdown": breakdown.to_dict(),
                "review": verdict.to_dict(),
                "data_sources": ["igdb", "steam_appdetails", "igdb_popscore"],
            }
        )
    return results


def run_discovery(
    *,
    mode: Mode = "dry-run",
    limit: int = 50,
    per_category: int | None = None,
    verify_steam: bool = True,
    selection: str = "relevance",
) -> dict[str, Any]:
    """selection:
      relevance — rank by demand/missing first (V5 default; no forced equal slices)
      balanced  — legacy round-robin across categories (debug only)
    """
    config.assert_prototype_safety()
    if mode not in ("dry-run", "stage"):
        raise ValueError("mode must be dry-run or stage")

    write_staging = mode == "stage"
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    if not config.CATALOG_DB.is_file():
        raise FileNotFoundError(f"Catalog DB missing: {config.CATALOG_DB}")

    index = CatalogIndex(config.CATALOG_DB)
    client = IgdbClient()
    client.ensure_token()
    verifier = SteamVerifier() if verify_steam else SteamVerifier(pause_sec=0)

    # --- Part 1: known problem regressions + prior 30 ---
    known = investigate_known_games(client, verifier, index) if verify_steam else []
    table30 = verify_prior_30(verifier, index) if verify_steam else []

    # --- Part 2: category pools (large) then select by relevance ---
    # Do not treat equal 25/category as production logic.
    per = per_category if per_category is not None else max(limit, 100)
    pool = max(200, limit * 2, 500)
    scored, fetch_stats = collect_categorized(client, per_category=per, pool=pool)
    fetch_stats["selection"] = selection
    fetch_stats["pool"] = pool
    processed = _process_scored(scored, index=index, verifier=verifier, client=client)

    def _sel_key(r: dict[str, Any]) -> tuple:
        bucket = (r.get("review") or {}).get("bucket") or ""
        pop = r.get("popularity") or {}
        steam = r.get("steam") or {}
        norm = pop.get("metric_norm")
        recs = steam.get("recommendations")
        return (
            0 if not r.get("in_quenly") else 1,
            0 if bucket == BUCKET_APPROVABLE else 1 if bucket == BUCKET_NEEDS_REVIEW else 2,
            0 if norm is not None else 1,
            -(float(norm) if norm is not None else 0.0),
            0 if recs is not None else 1,
            -(int(recs) if recs is not None else 0),
            -float((r.get("review") or {}).get("scan_priority") or 0),
        )

    if selection == "balanced":
        by_cat: dict[str, list[dict[str, Any]]] = {}
        for row in processed:
            cat = (row.get("popularity") or {}).get("category") or "other"
            by_cat.setdefault(cat, []).append(row)
        for cat in by_cat:
            by_cat[cat].sort(key=_sel_key)
        selected: list[dict[str, Any]] = []
        cats = list(by_cat.keys())
        while len(selected) < limit and any(by_cat.values()):
            for cat in list(cats):
                if len(selected) >= limit:
                    break
                bucket = by_cat.get(cat) or []
                if not bucket:
                    continue
                selected.append(bucket.pop(0))
    else:
        # Relevance: global sort, dedupe by igdb_id, take top `limit` (may be uneven across cats).
        seen: set[int] = set()
        selected = []
        for row in sorted(processed, key=_sel_key):
            gid = int(row["igdb_id"])
            if gid in seen:
                continue
            seen.add(gid)
            selected.append(row)
            if len(selected) >= limit:
                break

    # Guard: no future Steam coming_soon left in new_releases.
    bad_new = [
        r
        for r in selected
        if (r.get("popularity") or {}).get("category") == CATEGORY_NEW
        and (r.get("steam") or {}).get("coming_soon")
    ]
    for r in bad_new:
        (r.setdefault("popularity", {}))["category"] = CATEGORY_UPCOMING
        (r.setdefault("review", {}))["reason"] = "reclassified_future_out_of_new_releases"

    bucket_counts = Counter((r.get("review") or {}).get("bucket") for r in selected)
    table30_counts = Counter(r.get("bucket") for r in table30)
    cat_counts = Counter((r.get("popularity") or {}).get("category") for r in selected)
    wrong_steam = [k for k in known if not k.get("pass")]
    missing_quenly = sum(1 for r in selected if not r.get("in_quenly"))
    verified_new = [
        r
        for r in selected
        if (r.get("steam_resolution") or {}).get("status") == "verified"
        and not r.get("in_quenly")
    ]
    verified_new_n = len(verified_new)

    # Store coverage (local caches only) + import queues (identity separate from shop).
    store_index = LocalStoreIndex()
    coverage_report = analyze_candidates(selected, index=store_index)
    cov_by_id = {
        int(r["igdb_id"]): r for r in (coverage_report.get("results") or []) if r.get("igdb_id") is not None
    }
    for row in selected:
        cov = cov_by_id.get(int(row["igdb_id"])) or {
            "status": "unknown",
            "summary": "no local evidence",
            "hits": [],
            "shops_with_hits": [],
        }
        row["store_coverage"] = cov
    queue_report = assign_all(selected)

    reason_counts = Counter((r.get("review") or {}).get("reason") for r in verified_new)
    candidate_audit = {
        "verified_new_count": verified_new_n,
        "reason_breakdown": dict(reason_counts),
        "approvable_why_few": (
            "Most verified-new titles in the balanced batch are long-tail new/upcoming "
            "indies with unavailable Steam recommendation counts and zero/missing PopScore. "
            "Quality gates correctly hold them for review; thresholds were not lowered. "
            "recs=None is no longer mislabeled as 'too few recommendations'."
        ),
        "rows": [
            {
                "name": r.get("name"),
                "igdb_id": r.get("igdb_id"),
                "steam_appid": r.get("steam_appid"),
                "game_type": r.get("game_type"),
                "pc_release_date": (r.get("review") or {}).get("pc_release_date"),
                "category": (r.get("popularity") or {}).get("category"),
                "metric_norm": (r.get("popularity") or {}).get("metric_norm"),
                "steam_recommendations": (r.get("steam") or {}).get("recommendations"),
                "monetization": (r.get("review") or {}).get("monetization"),
                "in_quenly": r.get("in_quenly"),
                "match_confidence": (r.get("match") or {}).get("confidence"),
                "review_bucket": (r.get("review") or {}).get("bucket"),
                "review_reason": (r.get("review") or {}).get("reason"),
                "import_queue": (r.get("import_queue") or {}).get("queue"),
                "store_coverage": (r.get("store_coverage") or {}).get("status"),
            }
            for r in verified_new
        ],
    }

    top20 = []
    ranked = sorted(
        [r for r in selected if not r.get("in_quenly")],
        key=lambda x: -float((x.get("review") or {}).get("scan_priority") or 0),
    )[:20]
    for i, r in enumerate(ranked, 1):
        top20.append(
            {
                "rank": i,
                "name": r.get("name"),
                "igdb_id": r.get("igdb_id"),
                "steam_appid": r.get("steam_appid"),
                "priority": (r.get("review") or {}).get("scan_priority"),
                "import_queue": (r.get("import_queue") or {}).get("queue"),
                "store_coverage": (r.get("store_coverage") or {}).get("status"),
                "reason": (r.get("review") or {}).get("reason"),
                "bucket": (r.get("review") or {}).get("bucket"),
            }
        )

    # Load estimate (no production impact).
    load_estimate = {
        "igdb_requests_per_pass": (
            "≈ token + popularity_primitives(~4) + games batches + external_games "
            f"chunks for ~{per * 4} pool ids; typical 25–60 IGDB HTTP calls for limit={limit}"
        ),
        "steam_appdetails_per_pass": f"up to ~{limit + 40} (candidates + known probes)",
        "pass_wall_time_sec_estimate": "90–240s depending on Steam pause + IGDB rate limit",
        "staging_db_growth": "one row per unique igdb_id; approval log append-only",
        "memory": "feed CSV index held in-process during coverage (largest: kinguin/g2a ~10–18MB each)",
        "vps_risk": "none while local-only; do not enable production cron/IGDB without commercial OK",
        "rate_limit_handling": "IgdbClient retries/backoff; SteamVerifier unverified on failure",
        "partial_response": "missing Steam recs → insufficient_demand_signals, not rejection",
        "rerun_safety": "upsert by igdb_id; approved/rejected/deferred statuses preserved",
    }

    store: StagingStore | None = None
    run_id = None
    if write_staging:
        store = StagingStore()
        run_id = store.start_run(mode=mode, dry_run=False, limit_n=limit)
        for row in selected:
            rev = row.get("review") or {}
            pop = row.get("popularity") or {}
            match = row.get("match") or {}
            steam = row.get("steam") or {}
            reso = row.get("steam_resolution") or {}
            iq = row.get("import_queue") or {}
            cov = row.get("store_coverage") or {}
            staging_status = {
                BUCKET_APPROVABLE: "pending_review",
                BUCKET_NEEDS_REVIEW: "pending_review",
                BUCKET_F2P: "f2p_deferred",
                BUCKET_QUARANTINE: "quarantine",
                BUCKET_ALREADY: "already_in_catalog",
                BUCKET_REJECTED: "rejected",
            }.get(rev.get("bucket"), "pending_review")
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
                    "steam_verified": 1
                    if (reso.get("status") == "verified" and rev.get("steam_verified"))
                    else 0,
                    "scan_priority": rev.get("scan_priority"),
                    "staging_status": staging_status,
                    "release_status": "upcoming"
                    if steam.get("coming_soon")
                    else ("released" if steam.get("release_date") else "unknown"),
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

    approvable = [r for r in selected if (r.get("review") or {}).get("bucket") == BUCKET_APPROVABLE]
    rejected = [r for r in selected if (r.get("review") or {}).get("bucket") == BUCKET_REJECTED]

    # GO/NO-GO heuristic (V4: staging approval workflow ready)
    n_ok = len(approvable)
    n_rej = len(rejected)
    known_fail_n = len(wrong_steam)
    if known_fail_n:
        verdict = "NO-GO — known-problem Steam AppID regressions still failing"
        detail = f"Failing known titles: {[k.get('name') for k in wrong_steam]}"
    elif len(bad_new):
        verdict = "NO-GO — future releases leaked into NEW RELEASES"
        detail = "Category guard failed; fix reclassification before import."
    elif n_ok >= 3 and wrong_steam == []:
        verdict = "CONDITIONAL GO — V4 staging + approval ready; no production import"
        detail = (
            "Steam resolver no longer guesses AppIDs; store coverage is local-only; "
            "approval writes staging only. Commercial IGDB OK still required before VPS."
        )
    elif n_ok == 0:
        verdict = "NO-GO for import — zero APPROVABLE after Steam verification / quality gates"
        detail = (
            "Catalog already covers most PopScore tops; long-tail stays NEEDS_REVIEW. "
            "Continue filter iteration; do not import."
        )
    else:
        verdict = "CONDITIONAL GO — small APPROVABLE set; use approval UI for triage"
        detail = "Do not enable cron, scanners, or production writes."

    your_bf = next((r for r in table30 if r.get("igdb_id") == 165460 or r.get("name") == "Your Boyfriend"), None)
    report: dict[str, Any] = {
        "mode": mode,
        "wrote_staging": write_staging,
        "write_production": False,
        "enqueue_scanners": False,
        "run_id": run_id,
        "limit": limit,
        "fetch_stats": fetch_stats,
        "bucket_counts": dict(bucket_counts),
        "category_counts": dict(cat_counts),
        "known_problem_games": known,
        "known_problem_failures": wrong_steam,
        "verification_table_30": table30,
        "verification_30_counts": dict(table30_counts),
        "your_boyfriend_explanation": {
            "in_prior_30": your_bf,
            "why_prior_approvable_but_zero_in_50": (
                "Prior-30 used the old Visits/popular path without quality gate on popular; "
                "balanced 50 prefers Global Top Sellers / growth cohorts where Your Boyfriend "
                "usually does not appear, so it is absent from the 50 — not a silent reject."
            ),
        },
        "candidates": selected,
        "candidate_audit": candidate_audit,
        "import_queues": queue_report,
        "store_coverage": {
            "meta": coverage_report.get("meta"),
            "candidates_analyzed": coverage_report.get("candidates_analyzed"),
            "with_known_local_offer": coverage_report.get("with_known_local_offer"),
            "unknown_coverage": coverage_report.get("unknown_coverage"),
            "unknown_means": coverage_report.get("unknown_means"),
            "by_shop_candidate_hits": coverage_report.get("by_shop_candidate_hits"),
        },
        "top20_priority": top20,
        "load_estimate": load_estimate,
        "approvable_games": [
            {
                "name": r["name"],
                "igdb_id": r["igdb_id"],
                "steam_appid": r.get("steam_appid"),
                "priority": (r.get("review") or {}).get("scan_priority"),
                "priority_breakdown": r.get("priority_breakdown"),
                "category": (r.get("popularity") or {}).get("category"),
                "monetization": (r.get("review") or {}).get("monetization"),
                "reason": (r.get("review") or {}).get("reason"),
                "import_queue": (r.get("import_queue") or {}).get("queue"),
                "store_coverage": (r.get("store_coverage") or {}).get("status"),
            }
            for r in sorted(
                approvable,
                key=lambda x: -float((x.get("review") or {}).get("scan_priority") or 0),
            )
        ],
        "steam_istore": istore_credential_report().to_dict(),
        "summary": {
            "analyzed": len(selected),
            "popular_found": cat_counts.get("popular", 0),
            "trending_found": cat_counts.get("trending", 0),
            "new_releases_found": cat_counts.get("new_releases", 0),
            "upcoming_found": cat_counts.get("upcoming", 0),
            "missing_in_quenly": missing_quenly,
            "verified_new_candidates": verified_new_n,
            "wrong_steam_appid_in_known_set": len(wrong_steam),
            "approvable": n_ok,
            "rejected": n_rej,
            "needs_review": bucket_counts.get(BUCKET_NEEDS_REVIEW, 0),
            "already_exists": bucket_counts.get(BUCKET_ALREADY, 0),
            "f2p_deferred": bucket_counts.get(BUCKET_F2P, 0),
            "quarantine": bucket_counts.get(BUCKET_QUARANTINE, 0),
            "with_steam_appid": sum(1 for r in selected if r.get("steam_appid")),
            "steam_verified_true": sum(
                1
                for r in selected
                if (r.get("steam_resolution") or {}).get("status") == "verified"
            ),
            "future_in_new_releases": len(bad_new),
            "catalog_games": index.stats.games_total,
            "catalog_with_steam": index.stats.with_steam,
            "catalog_without_steam": index.stats.without_steam,
            "catalog_without_steam_rows": index.stats.without_steam_rows,
            "catalog_duplicate_steam": index.stats.duplicate_steam_appids,
            "import_queue_counts": queue_report.get("counts"),
            "store_known_local": coverage_report.get("with_known_local_offer"),
            "store_unknown": coverage_report.get("unknown_coverage"),
            "security_note": (
                "Secrets not embedded in this report. "
                "Token cache lives under gitignored staging/. "
                "APPROVE never publishes to production."
            ),
        },
        "go_nogo": {"verdict": verdict, "detail": detail},
        "commercial_igdb_note": (
            "Commercial use of IGDB requires prior agreement with IGDB (partner@igdb.com)."
        ),
        "safety": {
            "touched_games_table": False,
            "touched_offers_table": False,
            "touched_price_engine": False,
            "touched_scanners": False,
            "staging_db": str(config.STAGING_DB) if write_staging else None,
        },
    }

    html_path = render_html_report(report)
    json_path = config.REPORTS_DIR / f"discovery_run_{_stamp()}.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (config.REPORTS_DIR / "discovery_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Markdown companion
    md = config.REPORTS_DIR / "DISCOVERY_V2_GO_NOGO.md"
    lines = [
        "# IGDB Discovery v2 — results",
        "",
        f"**Verdict:** {verdict}",
        "",
        detail,
        "",
        f"- Mode: `{mode}` (staging writes: {write_staging})",
        f"- APPROVABLE: {n_ok}",
        f"- REJECTED: {n_rej}",
        f"- NEEDS_REVIEW: {bucket_counts.get(BUCKET_NEEDS_REVIEW, 0)}",
        f"- ALREADY_EXISTS: {bucket_counts.get(BUCKET_ALREADY, 0)}",
        f"- F2P_DEFERRED: {bucket_counts.get(BUCKET_F2P, 0)}",
        f"- QUARANTINE: {bucket_counts.get(BUCKET_QUARANTINE, 0)}",
        f"- HTML: `{html_path}`",
        "",
        "## Approvable titles",
        "",
    ]
    for g in report["approvable_games"][:40]:
        lines.append(
            f"- {g['name']} (igdb={g['igdb_id']}, steam={g['steam_appid']}, "
            f"cat={g['category']}, pay={g['monetization']}, prio={g['priority']})"
        )
    if not report["approvable_games"]:
        lines.append("_None_")
    lines += [
        "",
        "## Prior-30 verification buckets",
        "",
        f"`{dict(table30_counts)}`",
        "",
        "## Catalog anomalies (no Steam AppID)",
        "",
    ]
    for row in index.stats.without_steam_rows:
        lines.append(f"- id={row.get('id')} platform={row.get('platform')} title={row.get('title')}")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if write_staging and store is not None and run_id is not None:
        store.finish_run(run_id, report["summary"], str(html_path))

    logger.info("Discovery report: %s", html_path)
    return report


# Back-compat wrappers used by older entrypoint / tests.
def run_prototype(*, limit: int | None = None, dry_run: bool | None = None) -> dict[str, Any]:
    mode: Mode = "dry-run"
    if dry_run is False:
        mode = "stage"
    return run_discovery(mode=mode, limit=limit or config.PROTOTYPE_LIMIT)


def write_markdown_summary(report: dict[str, Any], path: Path | None = None) -> Path:
    path = path or (config.REPORTS_DIR / "DISCOVERY_V2_GO_NOGO.md")
    # Already written in run_discovery; ensure exists.
    if not path.is_file():
        path.write_text(
            f"# Discovery\n\n{(report.get('go_nogo') or {}).get('verdict')}\n",
            encoding="utf-8",
        )
    return path
