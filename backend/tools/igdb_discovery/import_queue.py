"""Smart import queue categories — separate from store-coverage status."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

QUEUE_HIGH = "HIGH_PRIORITY"
QUEUE_NEW = "NEW_RELEASE"
QUEUE_UPCOMING = "UPCOMING"
QUEUE_MANUAL = "MANUAL_REVIEW"
QUEUE_EXISTS = "ALREADY_EXISTS"

ALL_QUEUES = (QUEUE_HIGH, QUEUE_NEW, QUEUE_UPCOMING, QUEUE_MANUAL, QUEUE_EXISTS)


@dataclass
class QueueAssignment:
    queue: str
    reason: str
    priority: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_release_recent(pc_date: str | None, *, days: int = 45) -> bool:
    if not pc_date:
        return False
    raw = str(pc_date).strip()
    # Steam style "16 Oct, 2026" or ISO
    for fmt in ("%Y-%m-%d", "%d %b, %Y", "%d %b %Y", "%b %d, %Y"):
        try:
            dt = datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            return (now - timedelta(days=days)) <= dt <= (now + timedelta(days=2))
        except ValueError:
            continue
    return False


def assign_queue(row: dict[str, Any]) -> QueueAssignment:
    rev = row.get("review") or {}
    pop = row.get("popularity") or {}
    steam = row.get("steam") or {}
    reso = row.get("steam_resolution") or {}
    bucket = rev.get("bucket") or ""
    category = pop.get("category") or ""
    prio = float(rev.get("scan_priority") or 0)
    monetization = rev.get("monetization")

    if row.get("in_quenly") or bucket == "ALREADY_EXISTS":
        return QueueAssignment(QUEUE_EXISTS, "already_in_quenly_catalog", prio)

    if reso.get("status") == "ambiguous_manual_review":
        return QueueAssignment(
            QUEUE_MANUAL,
            "multiple_verified_steam_appids",
            prio,
        )

    if bucket in {"QUARANTINE", "REJECTED"} or reso.get("status") in {
        "none",
        "rejected_non_game",
        "unverified",
    }:
        return QueueAssignment(QUEUE_MANUAL, f"identity_{bucket or reso.get('status')}", prio)

    if steam.get("coming_soon") or category == "upcoming" or monetization == "unreleased":
        return QueueAssignment(
            QUEUE_UPCOMING,
            "future_pc_release_no_auto_publish",
            prio,
        )

    if bucket == "NEEDS_REVIEW":
        return QueueAssignment(QUEUE_MANUAL, rev.get("reason") or "needs_review", prio)

    # APPROVABLE / strong identity
    if category == "new_releases" or _parse_release_recent(rev.get("pc_release_date")):
        return QueueAssignment(QUEUE_NEW, "recent_pc_release_verified_steam", prio)

    # V5: HIGH_PRIORITY only via tri_score gate (demand + identity), never legacy total alone.
    tri = row.get("tri_score") or {}
    if tri.get("high_priority_eligible"):
        return QueueAssignment(
            QUEUE_HIGH,
            tri.get("high_priority_reason") or "tri_score_eligible",
            float((tri.get("demand") or {}).get("score") or prio),
        )

    if category in {"popular", "trending"} and bucket == "APPROVABLE":
        # Without tri_score, do not auto-promote on category alone.
        return QueueAssignment(
            QUEUE_MANUAL,
            "popular_missing_needs_demand_gate",
            prio,
        )

    if bucket == "APPROVABLE":
        return QueueAssignment(QUEUE_NEW, "approvable_verified_new", prio)

    return QueueAssignment(QUEUE_MANUAL, "fallback_manual", prio)


def assign_all(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    by_q: dict[str, list[dict[str, Any]]] = {q: [] for q in ALL_QUEUES}
    for row in candidates:
        a = assign_queue(row)
        row["import_queue"] = a.to_dict()
        by_q.setdefault(a.queue, []).append(
            {
                "igdb_id": row.get("igdb_id"),
                "name": row.get("name"),
                "steam_appid": row.get("steam_appid"),
                "priority": a.priority,
                "reason": a.reason,
                "review_bucket": (row.get("review") or {}).get("bucket"),
                "store_coverage_status": (row.get("store_coverage") or {}).get("status"),
            }
        )
    for q in by_q:
        by_q[q].sort(key=lambda x: -float(x.get("priority") or 0))
    return {
        "counts": {q: len(by_q[q]) for q in ALL_QUEUES},
        "queues": by_q,
        "note": (
            "import_queue is identity/priority routing; "
            "store_coverage is stored separately and never merged into queue status."
        ),
    }
