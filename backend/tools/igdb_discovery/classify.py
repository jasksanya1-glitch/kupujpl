"""Review buckets: APPROVABLE / NEEDS_REVIEW / REJECTED / ALREADY_EXISTS (+ F2P / quarantine)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from .fetchers import IgdbCandidate
from .matching import MatchResult, looks_like_edition_or_dlc
from .steam_verify import SteamCheck, is_non_game_steam_type

BUCKET_APPROVABLE = "APPROVABLE"
BUCKET_NEEDS_REVIEW = "NEEDS_REVIEW"
BUCKET_REJECTED = "REJECTED"
BUCKET_ALREADY = "ALREADY_EXISTS"
BUCKET_F2P = "F2P_DEFERRED"
BUCKET_QUARANTINE = "QUARANTINE"


@dataclass
class ReviewVerdict:
    bucket: str
    reason: str
    reasons: list[str] = field(default_factory=list)
    monetization: str | None = None  # paid | f2p | unknown | unreleased
    pc_release_date: str | None = None
    game_kind: str | None = None  # main_game | remake | …
    steam_verified: bool = False
    scan_priority: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_GAME_TYPE_LABEL = {
    0: "main_game",
    8: "remake",
    9: "remaster",
    11: "port",
    1: "dlc",
    2: "expansion",
    3: "bundle",
}


def _release_label(cand: IgdbCandidate, steam: SteamCheck | None) -> str | None:
    if steam and steam.release_date:
        return steam.release_date
    if cand.first_release_date:
        try:
            return datetime.fromtimestamp(cand.first_release_date, tz=timezone.utc).date().isoformat()
        except (OSError, OverflowError, ValueError):
            return str(cand.first_release_date)
    return None


def classify(
    cand: IgdbCandidate,
    match: MatchResult,
    steam: SteamCheck | None,
    *,
    category: str | None = None,
    metric_norm: float | None = None,
    steam_resolution_status: str | None = None,
) -> ReviewVerdict:
    reasons: list[str] = []
    kind = _GAME_TYPE_LABEL.get(cand.game_type or -1, f"type_{cand.game_type}")
    pc_date = _release_label(cand, steam)

    if match.status == "already_in_catalog":
        return ReviewVerdict(
            bucket=BUCKET_ALREADY,
            reason=match.reason,
            reasons=[match.reason],
            monetization=None,
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=bool(steam and steam.available and not steam.unverified),
        )

    if steam_resolution_status in {"none", "rejected_non_game"} and not cand.steam_appid:
        # Horizon Forbidden West base has no Steam row — quarantine base SKU;
        # Complete Edition is a separate sellable product.
        return ReviewVerdict(
            bucket=BUCKET_QUARANTINE,
            reason=steam_resolution_status or "no_steam_appid_quarantine_for_gog_epic_later",
            reasons=[steam_resolution_status or "no_steam_appid", "pc_edition_may_exist_separately"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=False,
        )

    if not cand.steam_appid:
        return ReviewVerdict(
            bucket=BUCKET_QUARANTINE,
            reason="no_steam_appid_quarantine_for_gog_epic_later",
            reasons=["no_steam_appid"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=False,
        )

    # AppID present without independent verification is NOT "verified".
    if steam_resolution_status and steam_resolution_status != "verified":
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason=f"steam_resolution_{steam_resolution_status}",
            reasons=[f"steam_resolution_{steam_resolution_status}", "appid_not_independently_verified"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=False,
        )

    if steam is None:
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason="steam_check_not_run",
            reasons=["steam_check_not_run"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=False,
        )

    if steam.unverified:
        # External source unavailable → unverified, not rejected.
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason="steam_unverified_api_unavailable",
            reasons=["steam_api_unavailable_or_rate_limited"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=False,
        )

    if not steam.available:
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason=steam.error or "steam_unavailable",
            reasons=[steam.error or "steam_unavailable"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=False,
        )

    if is_non_game_steam_type(steam.app_type):
        return ReviewVerdict(
            bucket=BUCKET_REJECTED,
            reason=f"steam_type_{steam.app_type}",
            reasons=[f"steam_type_{steam.app_type}"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=steam.app_type,
            steam_verified=True,
        )

    if steam.app_type and steam.app_type != "game":
        reasons.append(f"unexpected_steam_type_{steam.app_type}")

    if steam.windows is False:
        return ReviewVerdict(
            bucket=BUCKET_REJECTED,
            reason="not_windows_pc",
            reasons=["not_windows_pc"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=True,
        )

    if steam.title_ok is False:
        return ReviewVerdict(
            bucket=BUCKET_REJECTED,
            reason=f"title_mismatch:{steam.title_reason}",
            reasons=[f"title_mismatch:{steam.title_reason}"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=True,
        )

    # DLC/expansion types rejected; Complete/Deluxe bundles kept as separate SKUs.
    if cand.game_type in (1, 2, 4) or (
        looks_like_edition_or_dlc(cand.name) and cand.game_type in (1, 2, 4)
    ):
        return ReviewVerdict(
            bucket=BUCKET_REJECTED,
            reason="edition_or_dlc_igdb_type",
            reasons=["edition_or_dlc_igdb_type"],
            monetization="unknown",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=True,
        )

    # Monetization
    monetization = "unknown"
    if steam.coming_soon:
        monetization = "unreleased"
    elif steam.is_free is True:
        monetization = "f2p"
    elif steam.is_free is False:
        monetization = "paid"

    if monetization == "f2p":
        return ReviewVerdict(
            bucket=BUCKET_F2P,
            reason="f2p_deferred_not_deleted",
            reasons=["is_free_on_steam"],
            monetization=monetization,
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=True,
        )

    if match.status == "ambiguous":
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason=match.reason,
            reasons=[match.reason, "fuzzy_or_ambiguous_catalog_hit"],
            monetization=monetization,
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=True,
        )

    if steam.title_ok is None:
        reasons.append("title_check_incomplete")
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason="title_check_incomplete",
            reasons=reasons,
            monetization=monetization,
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=True,
        )

    if not pc_date and not steam.coming_soon:
        reasons.append("unknown_release_date")
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason="unknown_release_date",
            reasons=reasons,
            monetization=monetization,
            pc_release_date=None,
            game_kind=kind,
            steam_verified=True,
        )

    if reasons:
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason=";".join(reasons),
            reasons=reasons,
            monetization=monetization,
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=True,
        )

    # Future Steam page must never stay in NEW RELEASES.
    if category == "new_releases" and steam.coming_soon:
        return ReviewVerdict(
            bucket=BUCKET_NEEDS_REVIEW,
            reason="steam_coming_soon_misfiled_as_new_release",
            reasons=["move_to_upcoming", "steam_coming_soon"],
            monetization="unreleased",
            pc_release_date=pc_date,
            game_kind=kind,
            steam_verified=True,
        )

    # Quality gate: missing/low signals → NEEDS_REVIEW (not rejected).
    # Steam recommendations=None means "field unavailable", NOT "zero reviews".
    # Do not equate UNKNOWN demand with proven low demand.
    recs = steam.recommendations if steam else None
    recs_known = recs is not None
    missing_pop = metric_norm is None or float(metric_norm) <= 0.0
    has_pop = not missing_pop
    has_strong_recs = recs_known and int(recs) >= 20
    has_modest_recs = recs_known and int(recs) >= 5
    low_known_recs = recs_known and int(recs) < 20

    if category in {"new_releases", "upcoming"}:
        # At least one positive demand signal required for APPROVABLE.
        if has_pop or has_strong_recs:
            pass  # continue to APPROVABLE below
        elif monetization == "paid" and has_modest_recs:
            pass
        elif monetization == "paid" and not recs_known and missing_pop:
            # Paid + Steam verified but no PopScore and no recommendation count.
            return ReviewVerdict(
                bucket=BUCKET_NEEDS_REVIEW,
                reason="insufficient_demand_signals",
                reasons=[
                    "steam_recommendations_unavailable",
                    "missing_or_zero_popscore_norm",
                    "not_equated_to_zero_reviews",
                ],
                monetization=monetization,
                pc_release_date=pc_date,
                game_kind=kind,
                steam_verified=True,
            )
        elif monetization == "paid" and recs_known and int(recs) < 5 and missing_pop:
            return ReviewVerdict(
                bucket=BUCKET_NEEDS_REVIEW,
                reason="paid_but_too_few_steam_recommendations",
                reasons=[f"steam_recommendations={recs}", "weak_popularity_signal"],
                monetization=monetization,
                pc_release_date=pc_date,
                game_kind=kind,
                steam_verified=True,
            )
        elif missing_pop and (not recs_known or low_known_recs):
            return ReviewVerdict(
                bucket=BUCKET_NEEDS_REVIEW,
                reason="low_quality_signal_needs_review",
                reasons=[
                    "low_or_missing_popscore_norm",
                    (
                        f"steam_recommendations={recs}"
                        if recs_known
                        else "steam_recommendations_unavailable"
                    ),
                ],
                monetization=monetization,
                pc_release_date=pc_date,
                game_kind=kind,
                steam_verified=True,
            )

    # Technically fit — owner approval still required (not publish permission).
    return ReviewVerdict(
        bucket=BUCKET_APPROVABLE,
        reason="steam_verified_pc_game_not_in_catalog",
        reasons=["steam_appdetails_verified", "not_in_quenly", "owner_approval_still_required"],
        monetization=monetization,
        pc_release_date=pc_date,
        game_kind=kind,
        steam_verified=True,
    )
