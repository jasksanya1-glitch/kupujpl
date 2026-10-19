"""Fetch IGDB candidate sets: PopScore popular, recent PC, upcoming PC."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from . import config
from .client import IgdbClient

logger = logging.getLogger("igdb_discovery.fetchers")

# Mainline + remake/remaster/port. Bundles/editions allowed only with sellable markers.
ALLOWED_GAME_TYPES = frozenset({0, 8, 9, 11})  # main, remake, remaster, port
SELLABLE_EDITION_TYPES = frozenset({0, 3, 8, 9, 11})  # include bundle when edition-named
BLOCKED_GAME_TYPES = frozenset({1, 2, 4, 5, 6, 7, 13, 14})  # dlc, expansion, mod, …
_SELLABLE_EDITION_MARKERS = (
    "complete edition",
    "deluxe",
    "definitive",
    "goty",
    "game of the year",
    "gold edition",
    "ultimate",
    "remaster",
    "remastered",
    "remake",
    "director",
    "enhanced edition",
)


@dataclass
class IgdbCandidate:
    igdb_id: int
    name: str
    slug: str | None
    game_type: int | None
    first_release_date: int | None  # unix
    platforms: list[int] = field(default_factory=list)
    steam_appid: int | None = None
    parent_game: int | None = None
    version_parent: int | None = None
    pop_score: float | None = None
    source: str = ""  # popular | recent | upcoming
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _unix(dt: datetime) -> int:
    return int(dt.timestamp())


def _chunked(ids: list[int], size: int = 50) -> list[list[int]]:
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def fetch_top_popular_game_ids(
    client: IgdbClient,
    *,
    limit: int = 100,
    popularity_type: int = config.POPULARITY_TYPE_VISITS,
) -> list[tuple[int, float]]:
    """Return [(game_id, pop_value), ...] sorted by PopScore primitive."""
    body = (
        f"fields game_id,value,popularity_type;"
        f" sort value desc;"
        f" limit {int(limit)};"
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


def _hydrate_games(client: IgdbClient, game_ids: list[int]) -> list[dict[str, Any]]:
    if not game_ids:
        return []
    rows: list[dict[str, Any]] = []
    for chunk in _chunked(game_ids, 50):
        id_list = ",".join(str(i) for i in chunk)
        body = (
            "fields id,name,slug,game_type,category,first_release_date,platforms,"
            "parent_game,version_parent,summary,external_games;"
            f" where id = ({id_list});"
            f" limit {len(chunk)};"
        )
        rows.extend(client.query("games", body))
    return rows


def fetch_steam_appids(client: IgdbClient, game_ids: list[int]) -> dict[int, int]:
    """Deprecated naive mapper — prefer steam_resolve.resolve_many.

    Kept for transitional callers; uses external_game_source first and picks the
    **lowest** AppID per game (not last-write-wins) without Steam verification.
    """
    mapping: dict[int, int] = {}
    if not game_ids:
        return mapping
    for chunk in _chunked(game_ids, 40):
        id_list = ",".join(str(i) for i in chunk)
        body = (
            "fields game,uid,external_game_source,category,platform,id;"
            f" where game = ({id_list});"
            f" limit {min(500, len(chunk) * 12)};"
        )
        rows = client.query("external_games", body)
        per: dict[int, list[int]] = {}
        for row in rows:
            gid = row.get("game")
            uid = row.get("uid")
            if gid is None or uid is None:
                continue
            src = row.get("external_game_source")
            cat = row.get("category")
            is_steam = (src is not None and int(src) == config.STEAM_EXTERNAL_SOURCE) or (
                src is None and cat is not None and int(cat) == config.STEAM_EXTERNAL_SOURCE
            )
            if not is_steam:
                continue
            try:
                appid = int(str(uid).strip())
            except ValueError:
                continue
            per.setdefault(int(gid), []).append(appid)
        for gid, appids in per.items():
            mapping[gid] = min(appids)
    return mapping


def is_pc_mainline(raw: dict[str, Any]) -> tuple[bool, str]:
    """PC sellable product filter.

    - Base games, remakes, remasters, ports.
    - Complete/Deluxe/etc. editions kept as **separate** products (linked via
      version_parent) — not merged into the base game.
    - DLC / expansions / demos / soundtracks rejected.
    """
    platforms = raw.get("platforms") or []
    if config.PC_PLATFORM_ID not in platforms:
        return False, "not_pc"

    name = (raw.get("name") or "").lower()
    for marker in ("soundtrack", " ost", "artbook", "demo", "playtest", "trailer"):
        if marker in name:
            return False, f"name_marker_{marker.strip()}"

    gtype = raw.get("game_type")
    gtype_i = int(gtype) if gtype is not None else None
    if gtype_i is None:
        cat = raw.get("category")
        if cat is not None and int(cat) not in (0, 8, 9, 11):
            return False, f"legacy_category_{cat}"
        gtype_i = 0 if cat is None else int(cat)

    if gtype_i in BLOCKED_GAME_TYPES:
        return False, f"blocked_game_type_{gtype_i}"

    is_edition_named = any(m in name for m in _SELLABLE_EDITION_MARKERS)
    related = raw.get("version_parent") or raw.get("parent_game")

    if related:
        # DLC/expansion children already blocked by game_type.
        # Allow remake/remaster/port or explicitly named sellable editions.
        if gtype_i in (8, 9, 11):
            return True, "ok_related_remaster_or_remake"
        if is_edition_named and gtype_i in SELLABLE_EDITION_TYPES:
            return True, "ok_sellable_edition_product"
        return False, "related_non_sellable_child"

    if gtype_i not in ALLOWED_GAME_TYPES and not (
        is_edition_named and gtype_i in SELLABLE_EDITION_TYPES
    ):
        return False, f"unsupported_game_type_{gtype_i}"

    return True, "ok"


def _to_candidate(
    raw: dict[str, Any],
    *,
    source: str,
    steam_map: dict[int, int],
    pop: float | None = None,
) -> IgdbCandidate:
    gid = int(raw["id"])
    return IgdbCandidate(
        igdb_id=gid,
        name=str(raw.get("name") or f"igdb-{gid}"),
        slug=raw.get("slug"),
        game_type=int(raw["game_type"]) if raw.get("game_type") is not None else None,
        first_release_date=int(raw["first_release_date"]) if raw.get("first_release_date") else None,
        platforms=list(raw.get("platforms") or []),
        steam_appid=steam_map.get(gid),
        parent_game=raw.get("parent_game"),
        version_parent=raw.get("version_parent"),
        pop_score=pop,
        source=source,
        summary=(raw.get("summary") or None),
    )


def fetch_recent_pc_releases(client: IgdbClient, *, days: int = 30, limit: int = 100) -> list[dict[str, Any]]:
    now = _utcnow()
    start = _unix(now - timedelta(days=days))
    end = _unix(now)
    body = (
        "fields id,name,slug,game_type,category,first_release_date,platforms,"
        "parent_game,version_parent,summary;"
        f" where platforms = ({config.PC_PLATFORM_ID})"
        f" & first_release_date >= {start}"
        f" & first_release_date <= {end}"
        f" & version_parent = null;"
        " sort first_release_date desc;"
        f" limit {int(limit)};"
    )
    return client.query("games", body)


def fetch_upcoming_pc_releases(client: IgdbClient, *, days: int = 90, limit: int = 100) -> list[dict[str, Any]]:
    now = _utcnow()
    start = _unix(now)
    end = _unix(now + timedelta(days=days))
    body = (
        "fields id,name,slug,game_type,category,first_release_date,platforms,"
        "parent_game,version_parent,summary;"
        f" where platforms = ({config.PC_PLATFORM_ID})"
        f" & first_release_date > {start}"
        f" & first_release_date <= {end}"
        f" & version_parent = null;"
        " sort first_release_date asc;"
        f" limit {int(limit)};"
    )
    return client.query("games", body)


def collect_candidates(
    client: IgdbClient,
    *,
    limit: int = 50,
    popular_n: int = 100,
    recent_n: int = 80,
    upcoming_n: int = 80,
) -> tuple[list[IgdbCandidate], dict[str, Any]]:
    """Build a deduped candidate list capped at ``limit`` (prototype default 50)."""
    stats: dict[str, Any] = {
        "popular_fetched": 0,
        "recent_fetched": 0,
        "upcoming_fetched": 0,
        "filtered_out": {},
        "no_steam": 0,
        "started_at": _utcnow().isoformat(),
    }
    filtered: dict[str, int] = {}

    popular_pairs = fetch_top_popular_game_ids(client, limit=popular_n)
    stats["popular_fetched"] = len(popular_pairs)
    pop_map = {gid: val for gid, val in popular_pairs}
    popular_raw = _hydrate_games(client, [gid for gid, _ in popular_pairs])

    recent_raw = fetch_recent_pc_releases(client, limit=recent_n)
    stats["recent_fetched"] = len(recent_raw)
    upcoming_raw = fetch_upcoming_pc_releases(client, limit=upcoming_n)
    stats["upcoming_fetched"] = len(upcoming_raw)

    buckets: list[tuple[str, list[dict[str, Any]]]] = [
        ("popular", popular_raw),
        ("recent", recent_raw),
        ("upcoming", upcoming_raw),
    ]

    # Interleave sources for a balanced prototype set.
    selected: list[IgdbCandidate] = []
    seen: set[int] = set()
    all_ids: list[int] = []
    for _, rows in buckets:
        for row in rows:
            if row.get("id") is not None:
                all_ids.append(int(row["id"]))
    steam_map = fetch_steam_appids(client, list(dict.fromkeys(all_ids)))

    def _try_add(source: str, row: dict[str, Any]) -> bool:
        ok, reason = is_pc_mainline(row)
        if not ok:
            filtered[reason] = filtered.get(reason, 0) + 1
            return False
        gid = int(row["id"])
        if gid in seen:
            return False
        cand = _to_candidate(row, source=source, steam_map=steam_map, pop=pop_map.get(gid))
        if not cand.steam_appid:
            stats["no_steam"] = int(stats["no_steam"]) + 1
            # Still stage — match may fall back to title; flag in status later.
        seen.add(gid)
        selected.append(cand)
        return True

    # Round-robin: popular → recent → upcoming until limit.
    iterators = [(src, iter(rows)) for src, rows in buckets]
    while len(selected) < limit and iterators:
        next_iters: list[tuple[str, Any]] = []
        for src, it in iterators:
            if len(selected) >= limit:
                break
            try:
                while True:
                    row = next(it)
                    if _try_add(src, row):
                        break
            except StopIteration:
                continue
            next_iters.append((src, it))
        iterators = next_iters
        if not iterators:
            break

    stats["filtered_out"] = filtered
    stats["selected"] = len(selected)
    stats["finished_at"] = _utcnow().isoformat()
    return selected, stats
