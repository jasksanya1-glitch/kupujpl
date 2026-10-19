"""V5 separated scores: demand / identity / commercial — no invented popularity.

HIGH_PRIORITY requires strong demand + identity, not a high internal total alone.
Five Nights with Maids (98) audit: old score stacked category/verification/not-in-catalog
bonuses without confirmed demand or store evidence.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .popularity import (
    CATEGORY_NEW,
    CATEGORY_POPULAR,
    CATEGORY_TRENDING,
    CATEGORY_UPCOMING,
    ScoredCandidate,
)


@dataclass
class AxisScore:
    score: float | None  # None = insufficient data (not zero)
    confidence: float  # 0..1
    missing_signals: list[str] = field(default_factory=list)
    parts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TriScore:
    demand: AxisScore
    identity: AxisScore
    commercial: AxisScore
    high_priority_eligible: bool
    high_priority_reason: str
    legacy_total_audit: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "demand": self.demand.to_dict(),
            "identity": self.identity.to_dict(),
            "commercial": self.commercial.to_dict(),
            "high_priority_eligible": self.high_priority_eligible,
            "high_priority_reason": self.high_priority_reason,
            "legacy_total_audit": self.legacy_total_audit,
            "notes": self.notes,
        }


def audit_five_nights_style_legacy(
    *,
    metric_norm: float | None,
    steam_verified: bool,
    in_quenly: bool,
    is_free: bool | None,
    category: str,
    steam_recommendations: int | None,
    review_bucket: str,
) -> dict[str, Any]:
    """Explain how old scoring could reach ~98 without store coverage."""
    parts = []
    total = 0.0
    if metric_norm is not None:
        parts.append({"key": "normalized_popscore", "points": 30.0 * metric_norm})
        total += 30.0 * metric_norm
    if steam_verified:
        parts.append({"key": "steam_appid_verified", "points": 25.0})
        total += 25.0
    if not in_quenly:
        parts.append({"key": "not_in_quenly", "points": 15.0})
        total += 15.0
    if is_free is False:
        parts.append({"key": "paid", "points": 12.0})
        total += 12.0
    cat = {"new_releases": 5.0, "popular": 8.0, "trending": 6.0, "upcoming": 3.0}.get(category, 0)
    if cat:
        parts.append({"key": "category_bonus", "points": cat})
        total += cat
    if review_bucket == "APPROVABLE":
        parts.append({"key": "bucket_approvable", "points": 8.0})
        total += 8.0
    parts.append({"key": "released", "points": 3.0})
    total += 3.0
    return {
        "explained_total": round(total, 3),
        "parts": parts,
        "problem": (
            "Legacy total rewards verification + novelty + category bonuses even when "
            "Steam recommendations are missing and store coverage is UNKNOWN. "
            "V5 splits demand/identity/commercial and gates HIGH_PRIORITY on demand."
        ),
        "steam_recommendations": steam_recommendations,
        "store_coverage_not_in_legacy_score": True,
    }


def compute_tri_score(
    scored: ScoredCandidate,
    *,
    in_quenly: bool,
    is_free: bool | None,
    steam_resolution_status: str | None,
    steam_verified: bool,
    review_bucket: str,
    steam_recommendations: int | None,
    store_coverage_status: str | None,
    release_status: str | None,
    trending_insufficient_history: bool = False,
    legacy_total: float | None = None,
) -> TriScore:
    notes: list[str] = []

    # --- DEMAND ---
    d_parts: list[dict[str, Any]] = []
    d_missing: list[str] = []
    d_score: float | None = None
    d_conf = 0.0
    demand_points = 0.0
    demand_weight = 0.0

    if scored.metric_raw is not None and scored.metric_norm is not None:
        pts = 100.0 * float(scored.metric_norm)
        d_parts.append(
            {
                "key": "popscore_norm",
                "metric": scored.metric_name,
                "raw": scored.metric_raw,
                "norm": scored.metric_norm,
                "points": round(pts, 3),
            }
        )
        demand_points += pts
        demand_weight += 1.0
        d_conf += 0.45
    else:
        d_missing.append(f"popscore_unavailable:{scored.metric_name}")

    if steam_recommendations is None:
        d_missing.append("steam_recommendations_unavailable")
    elif steam_recommendations >= 1000:
        d_parts.append({"key": "steam_recs_high", "recs": steam_recommendations, "points": 100.0})
        demand_points += 100.0
        demand_weight += 1.0
        d_conf += 0.45
    elif steam_recommendations >= 50:
        d_parts.append({"key": "steam_recs_mid", "recs": steam_recommendations, "points": 55.0})
        demand_points += 55.0
        demand_weight += 1.0
        d_conf += 0.35
    elif steam_recommendations >= 5:
        d_parts.append({"key": "steam_recs_low", "recs": steam_recommendations, "points": 20.0})
        demand_points += 20.0
        demand_weight += 0.5
        d_conf += 0.2
    else:
        d_parts.append({"key": "steam_recs_very_low", "recs": steam_recommendations, "points": 5.0})
        demand_points += 5.0
        demand_weight += 0.25
        d_conf += 0.1

    if trending_insufficient_history and scored.category == CATEGORY_TRENDING:
        d_missing.append("trending_insufficient_history")
        d_conf = min(d_conf, 0.25)
        notes.append("trending_marked_insufficient_history")

    if demand_weight > 0:
        d_score = round(demand_points / demand_weight, 3)
        d_conf = min(1.0, d_conf)
    else:
        d_score = None
        d_conf = 0.0
        d_missing.append("no_confirmed_demand_signals")

    demand = AxisScore(score=d_score, confidence=round(d_conf, 3), missing_signals=d_missing, parts=d_parts)

    # --- IDENTITY ---
    i_parts: list[dict[str, Any]] = []
    i_missing: list[str] = []
    i_score = 0.0
    i_conf = 0.0
    if steam_resolution_status == "verified" and steam_verified:
        i_parts.append({"key": "steam_verified", "points": 90.0})
        i_score = 90.0
        i_conf = 0.95
    elif steam_resolution_status == "ambiguous_manual_review":
        i_parts.append({"key": "ambiguous_appids", "points": 35.0})
        i_score = 35.0
        i_conf = 0.4
        i_missing.append("multiple_verified_steam_appids")
    elif steam_resolution_status in {"none", "rejected_non_game"}:
        i_parts.append({"key": "no_valid_steam", "points": 10.0})
        i_score = 10.0
        i_conf = 0.7
        i_missing.append(str(steam_resolution_status))
    else:
        i_missing.append(f"steam_resolution:{steam_resolution_status}")
        i_score = 25.0
        i_conf = 0.3

    if in_quenly:
        i_parts.append({"key": "already_in_catalog", "note": "identity_ok_but_not_importable"})
    identity = AxisScore(
        score=round(i_score, 3), confidence=round(i_conf, 3), missing_signals=i_missing, parts=i_parts
    )

    # --- COMMERCIAL ---
    c_parts: list[dict[str, Any]] = []
    c_missing: list[str] = []
    c_score: float | None = None
    c_conf = 0.0
    if store_coverage_status == "known_offer":
        c_parts.append({"key": "local_store_evidence", "points": 70.0})
        c_score = 70.0
        c_conf = 0.7
    elif store_coverage_status == "unknown":
        c_missing.append("store_coverage_unknown_not_absence")
        c_score = None
        c_conf = 0.0
    else:
        c_missing.append("store_coverage_not_evaluated")
        c_score = None
        c_conf = 0.0

    if is_free is True:
        c_parts.append({"key": "f2p_low_price_compare_value", "points": -20.0})
        if c_score is not None:
            c_score = max(0.0, c_score - 20.0)
        notes.append("f2p_commercial_penalty_if_scored")
    elif is_free is False:
        c_parts.append({"key": "paid_sku", "points": 10.0})
        if c_score is not None:
            c_score = min(100.0, c_score + 10.0)
            c_conf = min(1.0, c_conf + 0.1)
    else:
        c_missing.append("monetization_unknown")

    if release_status == "upcoming":
        c_parts.append({"key": "upcoming_deferred_commercial", "note": "watchlist_only"})
    commercial = AxisScore(
        score=None if c_score is None else round(c_score, 3),
        confidence=round(c_conf, 3),
        missing_signals=c_missing,
        parts=c_parts,
    )

    # HIGH_PRIORITY gate — real demand + solid identity; store unknown OK but noted.
    eligible = False
    reason = "not_eligible"
    if in_quenly:
        reason = "already_in_catalog"
    elif review_bucket in {"REJECTED", "QUARANTINE", "F2P_DEFERRED"}:
        reason = f"bucket_{review_bucket}"
    elif identity.confidence < 0.8 or (identity.score or 0) < 80:
        reason = "identity_not_strong_enough"
    elif demand.score is None or demand.confidence < 0.35:
        reason = "demand_insufficient_or_unknown"
    elif demand.score < 40:
        reason = "demand_score_below_threshold"
    elif scored.category == CATEGORY_NEW and demand.confidence < 0.5:
        reason = "new_release_without_enough_demand_evidence"
    else:
        eligible = True
        reason = "demand_and_identity_confirmed"
        if store_coverage_status == "unknown":
            notes.append("high_priority_with_unknown_store_coverage")

    # Newness alone must not inflate demand.
    if scored.category == CATEGORY_NEW and demand.score is None:
        notes.append("new_without_demand_not_high_priority")

    return TriScore(
        demand=demand,
        identity=identity,
        commercial=commercial,
        high_priority_eligible=eligible,
        high_priority_reason=reason,
        legacy_total_audit=legacy_total,
        notes=notes,
    )


def assign_queue_v5(row: dict[str, Any]) -> dict[str, Any]:
    """Queue using tri-score; never equate ranking position with import permission."""
    from .import_queue import (
        QUEUE_EXISTS,
        QUEUE_HIGH,
        QUEUE_MANUAL,
        QUEUE_NEW,
        QUEUE_UPCOMING,
        QueueAssignment,
    )

    rev = row.get("review") or {}
    pop = row.get("popularity") or {}
    steam = row.get("steam") or {}
    tri = row.get("tri_score") or {}
    bucket = rev.get("bucket") or ""
    demand = (tri.get("demand") or {}).get("score")

    if row.get("in_quenly") or bucket == "ALREADY_EXISTS":
        a = QueueAssignment(QUEUE_EXISTS, "already_in_quenly_catalog", float(demand or 0))
    elif steam.get("coming_soon") or pop.get("category") == CATEGORY_UPCOMING:
        a = QueueAssignment(QUEUE_UPCOMING, "future_pc_release", float(demand or 0))
    elif tri.get("high_priority_eligible"):
        a = QueueAssignment(QUEUE_HIGH, tri.get("high_priority_reason") or "eligible", float(demand or 0))
    elif bucket == "APPROVABLE" and pop.get("category") == CATEGORY_NEW:
        a = QueueAssignment(QUEUE_NEW, "approvable_new_release", float(demand or 0))
    elif bucket == "APPROVABLE":
        a = QueueAssignment(QUEUE_NEW, "approvable_not_high_priority", float(demand or 0))
    else:
        a = QueueAssignment(QUEUE_MANUAL, rev.get("reason") or "needs_review", float(demand or 0))
    return a.to_dict()
