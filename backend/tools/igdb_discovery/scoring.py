"""Priority scoring with explicit explanations — no fake zeros for missing metrics."""
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
class PriorityBreakdown:
    total: float
    parts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def compute_priority_explained(
    scored: ScoredCandidate,
    *,
    in_quenly: bool,
    is_free: bool | None,
    steam_resolution_status: str | None,
    steam_verified: bool,
    review_bucket: str,
    steam_recommendations: int | None,
    release_status: str | None,
    trending_insufficient_history: bool = False,
) -> PriorityBreakdown:
    """Build priority with human-readable parts.

    Missing popularity is **not** treated as 0 contribution — it is skipped and noted.
    Having a Steam AppID without verification does not grant the verified bonus.
    """
    parts: list[dict[str, Any]] = []
    notes: list[str] = []
    total = 0.0

    if scored.metric_raw is None:
        notes.append(f"popularity_metric_missing:{scored.metric_name}")
    elif scored.metric_norm is None:
        notes.append(f"popularity_norm_unavailable:{scored.metric_name}")
    else:
        add = 30.0 * float(scored.metric_norm)
        parts.append(
            {
                "key": "normalized_popscore",
                "metric": scored.metric_name,
                "raw": scored.metric_raw,
                "norm": scored.metric_norm,
                "points": round(add, 3),
            }
        )
        total += add

    if trending_insufficient_history and scored.category == CATEGORY_TRENDING:
        notes.append("trending_insufficient_history")
        parts.append({"key": "trending_history_penalty", "points": -15.0})
        total -= 15.0

    if steam_verified and steam_resolution_status == "verified":
        parts.append({"key": "steam_appid_verified", "points": 25.0})
        total += 25.0
    elif scored.candidate.steam_appid and not steam_verified:
        notes.append("steam_appid_present_but_not_verified")
        parts.append({"key": "unverified_steam_appid", "points": 0.0})
    elif not scored.candidate.steam_appid:
        notes.append("no_steam_appid")

    if not in_quenly:
        parts.append({"key": "not_in_quenly", "points": 15.0})
        total += 15.0
    else:
        parts.append({"key": "already_in_quenly", "points": -40.0})
        total -= 40.0

    if is_free is False:
        parts.append({"key": "paid", "points": 12.0})
        total += 12.0
    elif is_free is True:
        parts.append({"key": "f2p", "points": -12.0})
        total -= 12.0
        notes.append("f2p_deferred_path")
    else:
        notes.append("monetization_unknown")

    if steam_recommendations is None:
        notes.append("steam_recommendations_unavailable")
    elif steam_recommendations >= 1000:
        parts.append({"key": "steam_reviews_high", "points": 10.0, "recs": steam_recommendations})
        total += 10.0
    elif steam_recommendations >= 50:
        parts.append({"key": "steam_reviews_mid", "points": 5.0, "recs": steam_recommendations})
        total += 5.0
    elif steam_recommendations >= 5:
        parts.append({"key": "steam_reviews_low", "points": 1.0, "recs": steam_recommendations})
        total += 1.0
    else:
        notes.append(f"steam_recommendations_very_low:{steam_recommendations}")

    cat_bonus = {
        CATEGORY_POPULAR: 8.0,
        CATEGORY_TRENDING: 6.0,
        CATEGORY_NEW: 5.0,
        CATEGORY_UPCOMING: 3.0,
    }.get(scored.category, 0.0)
    if cat_bonus:
        parts.append({"key": "category_bonus", "category": scored.category, "points": cat_bonus})
        total += cat_bonus

    if release_status == "released":
        parts.append({"key": "released", "points": 3.0})
        total += 3.0
    elif release_status == "upcoming":
        parts.append({"key": "upcoming", "points": 1.0})
        total += 1.0
    elif release_status == "unknown":
        notes.append("pc_release_date_unknown")

    if review_bucket == "APPROVABLE":
        parts.append({"key": "bucket_approvable", "points": 8.0})
        total += 8.0
    elif review_bucket == "NEEDS_REVIEW":
        parts.append({"key": "bucket_needs_review", "points": 1.0})
        total += 1.0
    elif review_bucket in {"REJECTED", "ALREADY_EXISTS", "QUARANTINE", "F2P_DEFERRED"}:
        parts.append({"key": f"bucket_{review_bucket.lower()}", "points": -50.0})
        total -= 50.0

    # Never invent a high score from empty popularity alone.
    if scored.metric_raw is None and steam_recommendations is None:
        notes.append("score_capped_due_to_missing_popularity_and_reviews")
        total = min(total, 20.0)

    scored.in_quenly = in_quenly
    scored.priority = round(total, 3)
    scored.notes = list(notes)
    return PriorityBreakdown(total=round(total, 3), parts=parts, notes=notes)
