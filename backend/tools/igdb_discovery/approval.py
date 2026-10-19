"""Local approval workflow — staging DB only, never production publish.

Lanes:
  test            — disposable; daily_sim / unit tests (separate SQLite)
  staging         — discovery candidates awaiting human review
  human_approved  — only real local-reviewer decisions (actor=human)

Sim/test actors must never write human_approved.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from . import config
from .staging import StagingStore

Action = Literal["approve", "reject", "defer", "revoke"]

PROTECTED_STATUSES = frozenset({"approved", "rejected", "deferred"})
ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "defer": "deferred",
    "revoke": "pending_review",
}

LANE_TEST = "test"
LANE_STAGING = "staging"
LANE_HUMAN = "human_approved"

SIM_ACTORS = frozenset({"daily_sim_probe", "test_harness", "simulation", "unit_test"})
HUMAN_ACTORS = frozenset({"local_reviewer", "human", "owner"})


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalStore:
    """Append-only decision log + candidate status updates (never production)."""

    def __init__(self, path: Path | None = None, *, lane: str = LANE_STAGING) -> None:
        self.path = path or config.STAGING_DB
        self.lane = lane
        self.path.parent.mkdir(parents=True, exist_ok=True)
        StagingStore(self.path)
        self._init_log()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init_log(self) -> None:
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS discovery_approval_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  igdb_id INTEGER NOT NULL,
                  action TEXT NOT NULL,
                  previous_status TEXT,
                  new_status TEXT NOT NULL,
                  actor TEXT NOT NULL DEFAULT 'local_reviewer',
                  note TEXT,
                  created_at TEXT NOT NULL,
                  lane TEXT,
                  approval_class TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_appr_igdb ON discovery_approval_log(igdb_id);
                CREATE INDEX IF NOT EXISTS idx_appr_created ON discovery_approval_log(created_at);
                """
            )
            cols = {r[1] for r in con.execute("PRAGMA table_info(discovery_candidates)")}
            for col, ddl in (
                ("import_queue", "TEXT"),
                ("import_queue_reason", "TEXT"),
                ("store_coverage_json", "TEXT"),
                ("store_coverage_status", "TEXT"),
                ("approval_note", "TEXT"),
                ("approved_at", "TEXT"),
                ("approval_lane", "TEXT"),
                ("approval_class", "TEXT"),
                ("approval_actor", "TEXT"),
            ):
                if col not in cols:
                    con.execute(f"ALTER TABLE discovery_candidates ADD COLUMN {col} {ddl}")
            log_cols = {r[1] for r in con.execute("PRAGMA table_info(discovery_approval_log)")}
            for col, ddl in (("lane", "TEXT"), ("approval_class", "TEXT")):
                if col not in log_cols:
                    con.execute(f"ALTER TABLE discovery_approval_log ADD COLUMN {col} {ddl}")

    def get_candidate(self, igdb_id: int) -> dict[str, Any] | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT * FROM discovery_candidates WHERE igdb_id=?",
                (int(igdb_id),),
            ).fetchone()
            return dict(row) if row else None

    def _classify_actor(self, actor: str) -> str:
        a = (actor or "").strip()
        if a in SIM_ACTORS or a.startswith("test_") or a.startswith("sim_"):
            return "simulation"
        if a in HUMAN_ACTORS:
            return "human"
        return "unknown"

    def decide(
        self,
        igdb_id: int,
        action: Action,
        *,
        actor: str = "local_reviewer",
        note: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        if action not in ACTION_TO_STATUS:
            return {"ok": False, "error": f"invalid_action:{action}"}

        approval_class = self._classify_actor(actor)
        # Test lane DB may use any actor; staging human_approved only via human actors.
        if self.lane == LANE_TEST:
            effective_lane = LANE_TEST
        elif action == "approve" and approval_class == "human":
            effective_lane = LANE_HUMAN
        elif action == "approve" and approval_class == "simulation":
            return {
                "ok": False,
                "error": "simulation_approve_blocked_on_staging",
                "hint": "Use TEST_STAGING_DB / ApprovalStore(lane=test) for sim probes",
            }
        else:
            effective_lane = self.lane

        new_status = ACTION_TO_STATUS[action]
        with self._connect() as con:
            row = con.execute(
                "SELECT igdb_id, name, staging_status, approval_class, approval_lane "
                "FROM discovery_candidates WHERE igdb_id=?",
                (int(igdb_id),),
            ).fetchone()
            if not row:
                return {"ok": False, "error": "candidate_not_in_staging", "igdb_id": igdb_id}
            prev = row["staging_status"]

            # Never silently overwrite a real human approval with sim revoke unless force+human.
            if (
                action == "revoke"
                and row["approval_class"] == "human"
                and approval_class != "human"
                and not force
            ):
                return {
                    "ok": False,
                    "error": "refuse_revoke_human_approval",
                    "igdb_id": igdb_id,
                    "approval_class": row["approval_class"],
                }

            if prev == "approved" and action == "approve" and not force:
                return {
                    "ok": False,
                    "error": "already_approved",
                    "igdb_id": igdb_id,
                    "staging_status": prev,
                    "hint": "pass force=true to re-log; production is never written",
                }

            now = _utcnow()
            keep_class = row["approval_class"]
            keep_lane = row["approval_lane"]
            if action == "approve":
                keep_class = approval_class
                keep_lane = effective_lane
            elif action == "revoke":
                keep_class = approval_class
                keep_lane = effective_lane

            con.execute(
                """
                UPDATE discovery_candidates
                SET staging_status=?, approval_note=?, approved_at=?,
                    approval_lane=?, approval_class=?, approval_actor=?, updated_at=?
                WHERE igdb_id=?
                """,
                (
                    new_status,
                    note,
                    now if action == "approve" else None,
                    keep_lane,
                    keep_class,
                    actor,
                    now,
                    int(igdb_id),
                ),
            )
            con.execute(
                """
                INSERT INTO discovery_approval_log
                  (igdb_id, action, previous_status, new_status, actor, note,
                   created_at, lane, approval_class)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    int(igdb_id),
                    action,
                    prev,
                    new_status,
                    actor,
                    note,
                    now,
                    effective_lane,
                    approval_class,
                ),
            )
        return {
            "ok": True,
            "igdb_id": igdb_id,
            "name": row["name"],
            "action": action,
            "previous_status": prev,
            "new_status": new_status,
            "lane": effective_lane,
            "approval_class": approval_class,
            "production_written": False,
            "message": "Recorded in local staging only — does NOT add game to Quenly production.",
        }

    def revoke_simulation_approval(
        self,
        igdb_id: int,
        *,
        note: str,
        actor: str = "v5_controlled_revoke",
    ) -> dict[str, Any]:
        """Revoke a simulation-only approval; refuse if human_approved."""
        row = self.get_candidate(igdb_id)
        if not row:
            return {"ok": False, "error": "not_found", "igdb_id": igdb_id}
        if row.get("approval_class") == "human" or row.get("approval_lane") == LANE_HUMAN:
            return {"ok": False, "error": "refuse_revoke_human_approval", "igdb_id": igdb_id}
        # Also refuse if log shows only human (legacy rows without class).
        with self._connect() as con:
            logs = con.execute(
                "SELECT actor, note, action FROM discovery_approval_log "
                "WHERE igdb_id=? ORDER BY id",
                (int(igdb_id),),
            ).fetchall()
        actors = [r["actor"] for r in logs if r["action"] == "approve"]
        notes = [r["note"] for r in logs if r["action"] == "approve"]
        sim_only = bool(actors) and all(
            (a in SIM_ACTORS or (n or "").startswith("daily_sim"))
            for a, n in zip(actors, notes, strict=False)
        ) or (
            (row.get("approval_note") or "").startswith("daily_sim")
            and row.get("staging_status") == "approved"
        )
        if not sim_only and row.get("approval_class") not in {None, "simulation", "unknown"}:
            return {"ok": False, "error": "not_confirmed_simulation_only", "igdb_id": igdb_id}
        return self.decide(
            igdb_id,
            "revoke",
            actor=actor,
            note=note,
            force=True,
        )

    def recent_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as con:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM discovery_approval_log ORDER BY id DESC LIMIT ?",
                    (limit,),
                )
            ]

    def summary(self) -> dict[str, Any]:
        with self._connect() as con:
            by_status = dict(
                con.execute(
                    "SELECT staging_status, COUNT(*) FROM discovery_candidates GROUP BY staging_status"
                ).fetchall()
            )
            by_lane = dict(
                con.execute(
                    "SELECT COALESCE(approval_lane,'?'), COUNT(*) FROM discovery_candidates "
                    "GROUP BY approval_lane"
                ).fetchall()
            )
            by_class = dict(
                con.execute(
                    "SELECT COALESCE(approval_class,'?'), COUNT(*) FROM discovery_candidates "
                    "GROUP BY approval_class"
                ).fetchall()
            )
            log_n = con.execute("SELECT COUNT(*) FROM discovery_approval_log").fetchone()[0]
        return {
            "db": str(self.path),
            "lane": self.lane,
            "by_staging_status": by_status,
            "by_approval_lane": by_lane,
            "by_approval_class": by_class,
            "approval_log_entries": int(log_n),
            "production_publish": False,
        }


def apply_decision_cli(igdb_id: int, action: Action, note: str | None = None) -> dict[str, Any]:
    return ApprovalStore(lane=LANE_STAGING).decide(
        igdb_id, action, note=note, actor="local_reviewer"
    )
