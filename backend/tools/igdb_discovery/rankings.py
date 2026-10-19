"""Game Rankings — independent of Discovery import permission.

Produces POPULAR / TRENDING / NEW_RELEASES / UPCOMING lists for catalog + missing
titles. Ranking position ≠ import approval.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import config
from .matching import CatalogIndex, normalize_title
from .popularity import (
    CATEGORY_NEW,
    CATEGORY_POPULAR,
    CATEGORY_TRENDING,
    CATEGORY_UPCOMING,
    collect_categorized,
)
from .store_coverage import LocalStoreIndex

logger = logging.getLogger("igdb_discovery.rankings")

RANK_POPULAR = "POPULAR"
RANK_TRENDING = "TRENDING"
RANK_NEW = "NEW_RELEASES"
RANK_UPCOMING = "UPCOMING"
ALL_RANKS = (RANK_POPULAR, RANK_TRENDING, RANK_NEW, RANK_UPCOMING)


@dataclass
class RankEntry:
    rank: int
    list_name: str
    igdb_id: int | None
    name: str
    steam_appid: int | None
    release_date: str | None
    source: str
    signals: dict[str, Any]
    in_quenly: bool
    quenly_game_id: int | None
    verification_status: str
    store_coverage_status: str
    cover_url: str | None
    updated_at: str
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cover(appid: int | None) -> str | None:
    if not appid:
        return None
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{int(appid)}/header.jpg"


def _init_rankings_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS ranking_runs (
              run_id TEXT PRIMARY KEY,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              mode TEXT,
              stats_json TEXT
            );
            CREATE TABLE IF NOT EXISTS ranking_entries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id TEXT NOT NULL,
              list_name TEXT NOT NULL,
              rank INTEGER NOT NULL,
              igdb_id INTEGER,
              name TEXT NOT NULL,
              steam_appid INTEGER,
              payload_json TEXT NOT NULL,
              UNIQUE(run_id, list_name, rank)
            );
            CREATE INDEX IF NOT EXISTS idx_rank_run_list ON ranking_entries(run_id, list_name);
            """
        )


class RankingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config.RANKINGS_DB
        _init_rankings_db(self.path)

    def save_run(self, run_id: str, *, mode: str, lists: dict[str, list[RankEntry]], stats: dict) -> None:
        now = _utcnow()
        with sqlite3.connect(self.path) as con:
            con.execute(
                "INSERT INTO ranking_runs(run_id, started_at, finished_at, mode, stats_json) VALUES(?,?,?,?,?)",
                (run_id, now, now, mode, json.dumps(stats, ensure_ascii=False)),
            )
            for list_name, entries in lists.items():
                for e in entries:
                    con.execute(
                        "INSERT INTO ranking_entries(run_id, list_name, rank, igdb_id, name, steam_appid, payload_json) "
                        "VALUES(?,?,?,?,?,?,?)",
                        (
                            run_id,
                            list_name,
                            e.rank,
                            e.igdb_id,
                            e.name,
                            e.steam_appid,
                            json.dumps(e.to_dict(), ensure_ascii=False),
                        ),
                    )


def _match_catalog(index: CatalogIndex, *, steam_appid: int | None, name: str) -> tuple[bool, int | None, str]:
    if steam_appid and steam_appid in index.by_steam:
        hit = index.by_steam[steam_appid]
        return True, hit.game_id, "steam_appid"
    nt = normalize_title(name)
    hits = index.by_norm_title.get(nt) or []
    if len(hits) == 1:
        return True, hits[0].game_id, "exact_title"
    if len(hits) > 1:
        return True, hits[0].game_id, "ambiguous_title"
    return False, None, "absent"


def build_rankings_offline_from_discovery(
    discovery_path: Path | None = None,
    *,
    top_n: int = 100,
) -> dict[str, Any]:
    """Rebuild ranking lists from last discovery report (no new IGDB calls)."""
    path = discovery_path or (config.REPORTS_DIR / "discovery_latest.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    cands = data.get("candidates") or []
    index = CatalogIndex(config.CATALOG_DB)
    store_idx = LocalStoreIndex()
    store_idx.load()
    run_id = f"rank_offline_{uuid.uuid4().hex[:10]}"
    updated = _utcnow()

    buckets: dict[str, list[dict[str, Any]]] = {
        RANK_POPULAR: [],
        RANK_TRENDING: [],
        RANK_NEW: [],
        RANK_UPCOMING: [],
    }
    for c in cands:
        cat = (c.get("popularity") or {}).get("category")
        key = {
            "popular": RANK_POPULAR,
            "trending": RANK_TRENDING,
            "new_releases": RANK_NEW,
            "upcoming": RANK_UPCOMING,
        }.get(cat or "")
        if key:
            buckets[key].append(c)

    # Also pull known problem / prior verified from report if present — skip.
    lists: dict[str, list[RankEntry]] = {}
    stats: dict[str, Any] = {
        "run_id": run_id,
        "mode": "offline_from_discovery",
        "source_report": str(path),
        "timestamp": updated,
        "top_n_requested": top_n,
        "padded": False,
        "note": "Lists show actual confirmed count; never artificially filled to 100.",
    }

    for list_name, rows in buckets.items():
        # Sort by demand-ish signals without inventing popularity.
        def sort_key(r: dict[str, Any]) -> tuple:
            pop = r.get("popularity") or {}
            steam = r.get("steam") or {}
            norm = pop.get("metric_norm")
            recs = steam.get("recommendations")
            # Prefer known demand; missing sorts last (not as zero).
            return (
                0 if norm is not None else 1,
                -(float(norm) if norm is not None else 0.0),
                0 if recs is not None else 1,
                -(int(recs) if recs is not None else 0),
            )

        rows_sorted = sorted(rows, key=sort_key)
        entries: list[RankEntry] = []
        seen: set[int] = set()
        for r in rows_sorted:
            gid = int(r["igdb_id"])
            if gid in seen:
                continue
            seen.add(gid)
            appid = r.get("steam_appid")
            in_q, qid, how = _match_catalog(index, steam_appid=appid, name=str(r.get("name") or ""))
            cov = store_idx.lookup(
                igdb_id=gid, name=str(r.get("name") or ""), steam_appid=appid
            )
            pop = r.get("popularity") or {}
            steam = r.get("steam") or {}
            reso = r.get("steam_resolution") or {}
            notes = []
            if list_name == RANK_TRENDING and pop.get("trending_insufficient_history"):
                notes.append("insufficient_history")
            if list_name == RANK_NEW and steam.get("coming_soon"):
                continue  # never put future into new releases
            entries.append(
                RankEntry(
                    rank=len(entries) + 1,
                    list_name=list_name,
                    igdb_id=gid,
                    name=str(r.get("name") or ""),
                    steam_appid=appid,
                    release_date=(r.get("review") or {}).get("pc_release_date") or steam.get("release_date"),
                    source=pop.get("metric_name") or list_name.lower(),
                    signals={
                        "metric_name": pop.get("metric_name"),
                        "metric_raw": pop.get("metric_raw"),
                        "metric_norm": pop.get("metric_norm"),
                        "steam_recommendations": steam.get("recommendations"),
                        "trending_d7": pop.get("trending_d7"),
                        "trending_d30": pop.get("trending_d30"),
                    },
                    in_quenly=in_q,
                    quenly_game_id=qid,
                    verification_status=reso.get("status") or "unknown",
                    store_coverage_status=cov.status,
                    cover_url=_cover(appid),
                    updated_at=updated,
                    notes=notes + ([f"catalog_match:{how}"] if in_q else []),
                )
            )
            if len(entries) >= top_n:
                break
        lists[list_name] = entries
        stats[f"{list_name}_count"] = len(entries)

    # Catalog-side NEW from local DB release dates (when column exists).
    catalog_new = _catalog_recent_releases(index, days=30, limit=top_n)
    if catalog_new:
        stats["catalog_new_releases_local"] = len(catalog_new)

    store = RankingsStore()
    store.save_run(run_id, mode="offline", lists=lists, stats=stats)

    # Summary vs Quenly for popular
    popular = lists.get(RANK_POPULAR) or []
    popular_in = sum(1 for e in popular if e.in_quenly)
    popular_missing = sum(1 for e in popular if not e.in_quenly)

    return {
        "run_id": run_id,
        "timestamp": updated,
        "lists": {k: [e.to_dict() for e in v] for k, v in lists.items()},
        "counts": {k: len(v) for k, v in lists.items()},
        "popular_in_quenly": popular_in,
        "popular_missing": popular_missing,
        "stats": stats,
        "ranking_position_is_not_import_permission": True,
    }


def _catalog_recent_releases(index: CatalogIndex, *, days: int, limit: int) -> list[dict[str, Any]]:
    """Optional local catalog scan — never invents popularity."""
    # CatalogIndex may not expose release dates; fail soft.
    try:
        con = sqlite3.connect(config.CATALOG_DB)
        cols = {r[1] for r in con.execute("PRAGMA table_info(games)")}
        if "release_date" not in cols and "first_release_date" not in cols:
            con.close()
            return []
        col = "release_date" if "release_date" in cols else "first_release_date"
        # Best-effort; schema varies.
        rows = con.execute(
            f"SELECT id, title, steam_appid, {col} FROM games WHERE steam_appid IS NOT NULL LIMIT ?",
            (limit * 5,),
        ).fetchall()
        con.close()
        return [{"id": r[0], "title": r[1], "steam_appid": r[2], "release": r[3]} for r in rows[:limit]]
    except Exception as exc:  # noqa: BLE001
        logger.info("catalog recent releases skipped: %s", exc)
        return []


def build_rankings_live(*, pool: int = 250, top_n: int = 100) -> dict[str, Any]:
    """Live IGDB ranking fetch — still staging-only, no production writes."""
    from .client import IgdbClient

    config.assert_prototype_safety()
    client = IgdbClient()
    client.ensure_token()
    # Large pool; do not force equal 25 slices into discovery import.
    scored, fetch_stats = collect_categorized(client, per_category=max(top_n, pool // 4), pool=pool)
    # Reuse offline path shape by synthesizing candidate-like dicts.
    fake_cands = []
    for s in scored:
        fake_cands.append(
            {
                "igdb_id": s.candidate.igdb_id,
                "name": s.candidate.name,
                "steam_appid": s.candidate.steam_appid,
                "popularity": {
                    "category": s.category,
                    "metric_name": s.metric_name,
                    "metric_raw": s.metric_raw,
                    "metric_norm": s.metric_norm,
                    "trending_d7": s.trending_d7,
                    "trending_d30": s.trending_d30,
                    "trending_insufficient_history": s.trending_insufficient_history,
                },
                "steam": {},
                "steam_resolution": {"status": "unknown"},
                "review": {},
            }
        )
    tmp = config.REPORTS_DIR / "_rankings_live_scratch.json"
    tmp.write_text(
        json.dumps({"candidates": fake_cands, "fetch_stats": fetch_stats}, ensure_ascii=False),
        encoding="utf-8",
    )
    result = build_rankings_offline_from_discovery(tmp, top_n=top_n)
    result["mode"] = "live"
    result["fetch_stats"] = fetch_stats
    return result
