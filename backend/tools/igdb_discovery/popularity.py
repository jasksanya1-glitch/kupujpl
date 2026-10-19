"""IGDB PopScore category fetch + within-metric normalization."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config
from .client import IgdbClient
from .fetchers import IgdbCandidate, _hydrate_games, is_pc_mainline
from .pop_history import trending_deltas

logger = logging.getLogger("igdb_discovery.popularity")

POP_VISITS = 1
POP_WANT_TO_PLAY = 2
POP_GLOBAL_TOP_SELLERS = 9
POP_WISHLISTED_UPCOMING = 10

CATEGORY_TRENDING = "trending"
CATEGORY_POPULAR = "popular"
CATEGORY_NEW = "new_releases"
CATEGORY_UPCOMING = "upcoming"
CATEGORY_UNKNOWN_RELEASE = "unknown_release_date"
CATEGORY_F2P = "f2p_deferred"


@dataclass
class ScoredCandidate:
    candidate: IgdbCandidate
    category: str
    metric_name: str
    metric_raw: float | None
    metric_norm: float | None  # 0..1 within same metric cohort; None if missing
    priority: float = 0.0
    in_quenly: bool = False
    notes: list[str] = field(default_factory=list)
    trending_d7: float | None = None
    trending_d30: float | None = None
    trending_insufficient_history: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["candidate"] = self.candidate.to_dict()
        return d


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _unix(dt: datetime) -> int:
    return int(dt.timestamp())


def fetch_pop_pairs(
    client: IgdbClient,
    popularity_type: int,
    *,
    limit: int = 150,
) -> list[tuple[int, float]]:
    body = (
        f"fields game_id,value,popularity_type;"
        f" sort value desc; limit {int(limit)};"
        f" where popularity_type = {int(popularity_type)};"
    )
    rows = client.query("popularity_primitives", body)
    out: list[tuple[int, float]] = []
    for row in rows:
        gid = row.get("game_id")
        if gid is None:
            continue
        out.append((int(gid), float(row.get("value") or 0.0)))
    return out


def normalize_within(values: list[float | None]) -> list[float | None]:
    """Min-max normalize; None stays None; all-zero cohort → all 0.0."""
    present = [v for v in values if v is not None]
    if not present:
        return [None for _ in values]
    lo, hi = min(present), max(present)
    out: list[float | None] = []
    for v in values:
        if v is None:
            out.append(None)
        elif hi <= lo:
            out.append(0.0 if hi == 0 else 1.0)
        else:
            out.append((v - lo) / (hi - lo))
    return out


def _to_candidate(raw: dict[str, Any], *, source: str, pop: float | None) -> IgdbCandidate:
    gid = int(raw["id"])
    return IgdbCandidate(
        igdb_id=gid,
        name=str(raw.get("name") or f"igdb-{gid}"),
        slug=raw.get("slug"),
        game_type=int(raw["game_type"]) if raw.get("game_type") is not None else None,
        first_release_date=int(raw["first_release_date"]) if raw.get("first_release_date") else None,
        platforms=list(raw.get("platforms") or []),
        steam_appid=None,  # filled after steam_resolve
        parent_game=raw.get("parent_game"),
        version_parent=raw.get("version_parent"),
        pop_score=pop,
        source=source,
        summary=(raw.get("summary") or None),
    )


def _build_scored(
    rows: list[dict[str, Any]],
    *,
    category: str,
    metric_name: str,
    raw_by_id: dict[int, float | None],
) -> list[ScoredCandidate]:
    ids = [int(r["id"]) for r in rows]
    raws = [raw_by_id.get(i) for i in ids]
    norms = normalize_within(raws)
    out: list[ScoredCandidate] = []
    for row, raw_v, norm_v in zip(rows, raws, norms):
        cand = _to_candidate(row, source=category, pop=raw_v)
        out.append(
            ScoredCandidate(
                candidate=cand,
                category=category,
                metric_name=metric_name,
                metric_raw=raw_v,
                metric_norm=norm_v,
            )
        )
    return out


def fetch_recent_pc(client: IgdbClient, *, days: int = 30, limit: int = 120) -> list[dict[str, Any]]:
    """Already-released PC titles only (first_release_date ≤ now)."""
    now = _utcnow()
    start, end = _unix(now - timedelta(days=days)), _unix(now)
    body = (
        "fields id,name,slug,game_type,category,first_release_date,platforms,"
        "parent_game,version_parent,summary;"
        f" where platforms = ({config.PC_PLATFORM_ID})"
        f" & first_release_date >= {start} & first_release_date <= {end};"
        " sort first_release_date desc;"
        f" limit {int(limit)};"
    )
    rows = []
    for row in client.query("games", body):
        ok, _ = is_pc_mainline(row)
        if not ok:
            continue
        fr = row.get("first_release_date")
        if fr is None or int(fr) > end:
            continue  # never allow future into new releases
        rows.append(row)
    return rows


def fetch_upcoming_pc(client: IgdbClient, *, days: int = 90, limit: int = 120) -> list[dict[str, Any]]:
    now = _utcnow()
    start, end = _unix(now), _unix(now + timedelta(days=days))
    body = (
        "fields id,name,slug,game_type,category,first_release_date,platforms,"
        "parent_game,version_parent,summary;"
        f" where platforms = ({config.PC_PLATFORM_ID})"
        f" & first_release_date > {start} & first_release_date <= {end};"
        " sort first_release_date asc;"
        f" limit {int(limit)};"
    )
    rows = []
    for row in client.query("games", body):
        ok, _ = is_pc_mainline(row)
        if ok:
            rows.append(row)
    return rows


def collect_categorized(
    client: IgdbClient,
    *,
    per_category: int = 25,
    pool: int = 150,
) -> tuple[list[ScoredCandidate], dict[str, Any]]:
    stats: dict[str, Any] = {"started_at": _utcnow().isoformat(), "categories": {}}

    want = fetch_pop_pairs(client, POP_WANT_TO_PLAY, limit=pool)
    sellers = fetch_pop_pairs(client, POP_GLOBAL_TOP_SELLERS, limit=pool)
    wishlist = fetch_pop_pairs(client, POP_WISHLISTED_UPCOMING, limit=pool)
    visits = fetch_pop_pairs(client, POP_VISITS, limit=pool)

    want_map = dict(want)
    sellers_map = dict(sellers)
    wish_map = dict(wishlist)
    visits_map = dict(visits)

    trend_meta = trending_deltas(POP_WANT_TO_PLAY, want)
    stats["trending_meta"] = {
        "insufficient_history": trend_meta["insufficient_history"],
        "baseline_7d": trend_meta["baseline_7d"],
        "baseline_30d": trend_meta["baseline_30d"],
        "today": trend_meta["today"],
    }

    hydrate_ids = list(
        dict.fromkeys(
            [i for i, _ in want[:pool]]
            + [i for i, _ in sellers[:pool]]
            + [i for i, _ in wishlist[:pool]]
            + [i for i, _ in visits[: min(80, pool)]]
        )
    )
    hydrated = {int(r["id"]): r for r in _hydrate_games(client, hydrate_ids)}

    recent_rows = fetch_recent_pc(client, limit=pool)
    upcoming_rows = fetch_upcoming_pc(client, limit=pool)

    def pick_pc_from_pairs(
        pairs: list[tuple[int, float]],
        *,
        category: str,
        metric_name: str,
        raw_map: dict[int, float],
        n: int,
        require_growth: bool = False,
    ) -> list[ScoredCandidate]:
        rows: list[dict[str, Any]] = []
        growth = trend_meta["growth"]
        for gid, _ in pairs:
            raw = hydrated.get(gid)
            if not raw:
                continue
            ok, _ = is_pc_mainline(raw)
            if not ok:
                continue
            if require_growth:
                g = growth.get(gid) or {}
                if trend_meta["insufficient_history"]:
                    # Still include but flag later — do not pretend trending.
                    pass
                else:
                    d7, d30 = g.get("d7"), g.get("d30")
                    if (d7 is None or d7 <= 0) and (d30 is None or d30 <= 0):
                        continue
            rows.append(raw)
            if len(rows) >= max(n * 5, n):
                break
        scored = _build_scored(
            rows[: max(n * 3, n)],
            category=category,
            metric_name=metric_name,
            raw_by_id={k: raw_map.get(k) for k in [int(r["id"]) for r in rows]},
        )
        for s in scored:
            g = (trend_meta["growth"] or {}).get(s.candidate.igdb_id) or {}
            s.trending_d7 = g.get("d7")  # type: ignore[assignment]
            s.trending_d30 = g.get("d30")  # type: ignore[assignment]
            s.trending_insufficient_history = bool(trend_meta["insufficient_history"])
            if category == CATEGORY_TRENDING and trend_meta["insufficient_history"]:
                s.notes.append("insufficient_history")
                s.metric_name = "want_to_play_insufficient_history"
        return scored[: max(n * 2, n)]

    trending = pick_pc_from_pairs(
        want,
        category=CATEGORY_TRENDING,
        metric_name="want_to_play_growth" if not trend_meta["insufficient_history"] else "want_to_play",
        raw_map=want_map,
        n=per_category,
        require_growth=not trend_meta["insufficient_history"],
    )

    popular = pick_pc_from_pairs(
        sellers if sellers else visits,
        category=CATEGORY_POPULAR,
        metric_name="global_top_sellers" if sellers else "visits",
        raw_map=sellers_map if sellers else visits_map,
        n=per_category,
        require_growth=False,
    )

    # New releases: visits when known, else None (not zero).
    recent_raw: dict[int, float | None] = {
        int(r["id"]): visits_map.get(int(r["id"])) for r in recent_rows
    }
    new_releases = _build_scored(
        recent_rows[: per_category * 3],
        category=CATEGORY_NEW,
        metric_name="visits",
        raw_by_id=recent_raw,
    )[: max(per_category * 2, per_category)]

    up_raw: dict[int, float | None] = {
        int(r["id"]): wish_map.get(int(r["id"])) for r in upcoming_rows
    }
    upcoming = _build_scored(
        upcoming_rows[: per_category * 3],
        category=CATEGORY_UPCOMING,
        metric_name="most_wishlisted_upcoming",
        raw_by_id=up_raw,
    )[: max(per_category * 2, per_category)]

    all_scored = trending + popular + new_releases + upcoming
    stats["categories"] = {
        CATEGORY_TRENDING: len(trending),
        CATEGORY_POPULAR: len(popular),
        CATEGORY_NEW: len(new_releases),
        CATEGORY_UPCOMING: len(upcoming),
    }
    stats["finished_at"] = _utcnow().isoformat()
    return all_scored, stats


# Back-compat name used by older scoring imports / tests
def compute_priority(*args: Any, **kwargs: Any) -> float:
    from .scoring import compute_priority_explained

    scored = args[0] if args else kwargs["scored"]
    br = compute_priority_explained(
        scored,
        in_quenly=kwargs.get("in_quenly", False),
        is_free=kwargs.get("is_free"),
        steam_resolution_status="verified" if kwargs.get("steam_verified") else None,
        steam_verified=bool(kwargs.get("steam_verified")),
        review_bucket=kwargs.get("review_bucket", "NEEDS_REVIEW"),
        steam_recommendations=None,
        release_status=None,
        trending_insufficient_history=bool(getattr(scored, "trending_insufficient_history", False)),
    )
    return br.total
