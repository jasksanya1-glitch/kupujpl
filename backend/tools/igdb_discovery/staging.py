"""Isolated staging SQLite — never writes production games/offers."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

PROTECTED_STAGING = frozenset({"approved", "rejected", "deferred"})

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS discovery_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  igdb_id INTEGER NOT NULL UNIQUE,
  name TEXT NOT NULL,
  slug TEXT,
  steam_appid INTEGER,
  game_type INTEGER,
  first_release_date INTEGER,
  category TEXT,
  metric_name TEXT,
  metric_raw REAL,
  metric_norm REAL,
  source TEXT NOT NULL,
  pop_score REAL,
  match_status TEXT NOT NULL,
  match_confidence REAL,
  match_reason TEXT,
  match_method TEXT,
  matched_game_id INTEGER,
  matched_title TEXT,
  review_bucket TEXT,
  review_reason TEXT,
  monetization TEXT,
  steam_name TEXT,
  steam_type TEXT,
  steam_verified INTEGER,
  scan_priority REAL,
  staging_status TEXT NOT NULL DEFAULT 'pending_review',
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS discovery_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  mode TEXT,
  dry_run INTEGER NOT NULL,
  limit_n INTEGER NOT NULL,
  stats_json TEXT,
  report_path TEXT
);
"""

EXTRA_CANDIDATE_COLS = [
    ("category", "TEXT"),
    ("metric_name", "TEXT"),
    ("metric_raw", "REAL"),
    ("metric_norm", "REAL"),
    ("review_bucket", "TEXT"),
    ("review_reason", "TEXT"),
    ("monetization", "TEXT"),
    ("steam_name", "TEXT"),
    ("steam_type", "TEXT"),
    ("steam_verified", "INTEGER"),
    ("scan_priority", "REAL"),
    ("release_status", "TEXT"),
    ("priority_breakdown_json", "TEXT"),
    ("steam_resolution_json", "TEXT"),
    ("data_sources", "TEXT"),
    ("import_queue", "TEXT"),
    ("import_queue_reason", "TEXT"),
    ("store_coverage_json", "TEXT"),
    ("store_coverage_status", "TEXT"),
    ("approval_note", "TEXT"),
    ("approved_at", "TEXT"),
]

INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_disc_status ON discovery_candidates(staging_status);
CREATE INDEX IF NOT EXISTS idx_disc_bucket ON discovery_candidates(review_bucket);
CREATE INDEX IF NOT EXISTS idx_disc_steam ON discovery_candidates(steam_appid);
CREATE INDEX IF NOT EXISTS idx_disc_match ON discovery_candidates(match_status);
CREATE INDEX IF NOT EXISTS idx_disc_queue ON discovery_candidates(import_queue);
"""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class StagingStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.STAGING_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with self._connect() as con:
            con.executescript(TABLE_SQL)
            cols = {r[1] for r in con.execute("PRAGMA table_info(discovery_candidates)")}
            for col, ddl in EXTRA_CANDIDATE_COLS:
                if col not in cols:
                    con.execute(f"ALTER TABLE discovery_candidates ADD COLUMN {col} {ddl}")
            run_cols = {r[1] for r in con.execute("PRAGMA table_info(discovery_runs)")}
            if "mode" not in run_cols:
                con.execute("ALTER TABLE discovery_runs ADD COLUMN mode TEXT")
            con.executescript(INDEX_SQL)

    def upsert_row(self, row: dict[str, Any]) -> None:
        """Upsert discovery row. Preserves manual approval/reject/defer status."""
        now = _utcnow()
        payload = json.dumps(row.get("payload") or row, ensure_ascii=False)
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO discovery_candidates (
                  igdb_id, name, slug, steam_appid, game_type, first_release_date,
                  category, metric_name, metric_raw, metric_norm,
                  source, pop_score, match_status, match_confidence, match_reason,
                  match_method, matched_game_id, matched_title,
                  review_bucket, review_reason, monetization,
                  steam_name, steam_type, steam_verified, scan_priority,
                  staging_status, release_status, priority_breakdown_json,
                  steam_resolution_json, data_sources,
                  import_queue, import_queue_reason,
                  store_coverage_json, store_coverage_status,
                  payload_json, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(igdb_id) DO UPDATE SET
                  name=excluded.name,
                  slug=excluded.slug,
                  steam_appid=excluded.steam_appid,
                  game_type=excluded.game_type,
                  first_release_date=excluded.first_release_date,
                  category=excluded.category,
                  metric_name=excluded.metric_name,
                  metric_raw=excluded.metric_raw,
                  metric_norm=excluded.metric_norm,
                  source=excluded.source,
                  pop_score=excluded.pop_score,
                  match_status=excluded.match_status,
                  match_confidence=excluded.match_confidence,
                  match_reason=excluded.match_reason,
                  match_method=excluded.match_method,
                  matched_game_id=excluded.matched_game_id,
                  matched_title=excluded.matched_title,
                  review_bucket=excluded.review_bucket,
                  review_reason=excluded.review_reason,
                  monetization=excluded.monetization,
                  steam_name=excluded.steam_name,
                  steam_type=excluded.steam_type,
                  steam_verified=excluded.steam_verified,
                  scan_priority=excluded.scan_priority,
                  staging_status=CASE
                    WHEN discovery_candidates.staging_status IN ('approved','rejected','deferred')
                    THEN discovery_candidates.staging_status
                    ELSE excluded.staging_status
                  END,
                  release_status=excluded.release_status,
                  priority_breakdown_json=excluded.priority_breakdown_json,
                  steam_resolution_json=excluded.steam_resolution_json,
                  data_sources=excluded.data_sources,
                  import_queue=excluded.import_queue,
                  import_queue_reason=excluded.import_queue_reason,
                  store_coverage_json=excluded.store_coverage_json,
                  store_coverage_status=excluded.store_coverage_status,
                  payload_json=excluded.payload_json,
                  updated_at=excluded.updated_at
                """,
                (
                    row["igdb_id"],
                    row["name"],
                    row.get("slug"),
                    row.get("steam_appid"),
                    row.get("game_type"),
                    row.get("first_release_date"),
                    row.get("category"),
                    row.get("metric_name"),
                    row.get("metric_raw"),
                    row.get("metric_norm"),
                    row.get("source") or row.get("category") or "unknown",
                    row.get("pop_score"),
                    row.get("match_status"),
                    row.get("match_confidence"),
                    row.get("match_reason"),
                    row.get("match_method"),
                    row.get("matched_game_id"),
                    row.get("matched_title"),
                    row.get("review_bucket"),
                    row.get("review_reason"),
                    row.get("monetization"),
                    row.get("steam_name"),
                    row.get("steam_type"),
                    1 if row.get("steam_verified") else 0,
                    row.get("scan_priority"),
                    row.get("staging_status") or "pending_review",
                    row.get("release_status"),
                    row.get("priority_breakdown_json"),
                    row.get("steam_resolution_json"),
                    row.get("data_sources"),
                    row.get("import_queue"),
                    row.get("import_queue_reason"),
                    row.get("store_coverage_json"),
                    row.get("store_coverage_status"),
                    payload,
                    now,
                    now,
                ),
            )

    def start_run(self, *, mode: str, dry_run: bool, limit_n: int) -> int:
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO discovery_runs (started_at, mode, dry_run, limit_n) VALUES (?,?,?,?)",
                (_utcnow(), mode, 1 if dry_run else 0, limit_n),
            )
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, stats: dict[str, Any], report_path: str | None) -> None:
        with self._connect() as con:
            con.execute(
                "UPDATE discovery_runs SET finished_at=?, stats_json=?, report_path=? WHERE id=?",
                (_utcnow(), json.dumps(stats, ensure_ascii=False), report_path, run_id),
            )

    def summary(self) -> dict[str, Any]:
        with self._connect() as con:
            by_bucket = dict(
                con.execute(
                    "SELECT COALESCE(review_bucket,'?'), COUNT(*) FROM discovery_candidates GROUP BY review_bucket"
                ).fetchall()
            )
            by_status = dict(
                con.execute(
                    "SELECT staging_status, COUNT(*) FROM discovery_candidates GROUP BY staging_status"
                ).fetchall()
            )
            by_queue = dict(
                con.execute(
                    "SELECT COALESCE(import_queue,'?'), COUNT(*) FROM discovery_candidates GROUP BY import_queue"
                ).fetchall()
            )
            approvable = [
                dict(r)
                for r in con.execute(
                    "SELECT igdb_id, name, steam_appid, category, scan_priority, monetization "
                    "FROM discovery_candidates WHERE review_bucket='APPROVABLE' "
                    "ORDER BY scan_priority DESC LIMIT 100"
                )
            ]
        return {
            "staging_db": str(self.path),
            "by_review_bucket": by_bucket,
            "by_staging_status": by_status,
            "by_import_queue": by_queue,
            "approvable": approvable,
        }

    def count_by_igdb(self) -> int:
        with self._connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM discovery_candidates").fetchone()[0])

    def get_protected_statuses(self) -> dict[int, str]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT igdb_id, staging_status FROM discovery_candidates "
                "WHERE staging_status IN ('approved','rejected','deferred')"
            ).fetchall()
            return {int(r[0]): str(r[1]) for r in rows}
