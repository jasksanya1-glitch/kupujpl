"""Resolve Steam AppID from IGDB external_games with Steam verification.

Never use lowest AppID as proof of correctness. When multiple verified
candidates remain after type/title/edition/catalog checks → manual review.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from . import config
from .client import IgdbClient
from .fetchers import _chunked
from .steam_verify import SteamVerifier, is_non_game_steam_type, titles_compatible

logger = logging.getLogger("igdb_discovery.steam_resolve")


@dataclass
class SteamExternalHit:
    igdb_game_id: int
    appid: int
    external_id: int | None
    external_name: str | None
    platform: int | None
    source_field: str  # external_game_source | legacy_category
    url: str | None = None


@dataclass
class SteamResolution:
    igdb_game_id: int
    igdb_name: str
    appid: int | None
    status: str
    # verified | none | unverified | ambiguous_manual_review | rejected_non_game
    confidence: float
    reason: str
    steam_name: str | None = None
    steam_type: str | None = None
    candidates: list[int] = field(default_factory=list)
    rejected: list[dict[str, Any]] = field(default_factory=list)
    preferred_because: list[str] = field(default_factory=list)
    ambiguous_appids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_steam_external_hits(
    client: IgdbClient,
    game_ids: list[int],
) -> dict[int, list[SteamExternalHit]]:
    out: dict[int, list[SteamExternalHit]] = {int(g): [] for g in game_ids}
    if not game_ids:
        return out

    for chunk in _chunked(list(dict.fromkeys(int(g) for g in game_ids)), 40):
        id_list = ",".join(str(i) for i in chunk)
        body = (
            "fields id,game,name,uid,url,platform,external_game_source,category;"
            f" where game = ({id_list});"
            f" limit {min(500, len(chunk) * 12)};"
        )
        rows = client.query("external_games", body)
        for row in rows:
            gid = row.get("game")
            uid = row.get("uid")
            if gid is None or uid is None:
                continue
            src = row.get("external_game_source")
            cat = row.get("category")
            is_steam = False
            source_field = "external_game_source"
            if src is not None and int(src) == config.STEAM_EXTERNAL_SOURCE:
                is_steam = True
            elif src is None and cat is not None and int(cat) == config.STEAM_EXTERNAL_SOURCE:
                is_steam = True
                source_field = "legacy_category"
            if not is_steam:
                continue
            try:
                appid = int(str(uid).strip())
            except ValueError:
                continue
            out.setdefault(int(gid), []).append(
                SteamExternalHit(
                    igdb_game_id=int(gid),
                    appid=appid,
                    external_id=int(row["id"]) if row.get("id") is not None else None,
                    external_name=row.get("name"),
                    platform=int(row["platform"]) if row.get("platform") is not None else None,
                    source_field=source_field,
                    url=row.get("url"),
                )
            )
    return out


def resolve_steam_appid(
    *,
    igdb_game_id: int,
    igdb_name: str,
    hits: list[SteamExternalHit],
    verifier: SteamVerifier,
    catalog_steam_ids: set[int] | None = None,
) -> SteamResolution:
    """Resolve Steam AppID or send to manual review — never guess."""
    catalog_steam_ids = catalog_steam_ids or set()
    ordered: list[SteamExternalHit] = []
    seen: set[int] = set()
    for h in sorted(hits, key=lambda x: (x.external_id is None, x.external_id or 10**12)):
        if h.appid in seen:
            continue
        seen.add(h.appid)
        ordered.append(h)

    if not ordered:
        return SteamResolution(
            igdb_game_id=igdb_game_id,
            igdb_name=igdb_name,
            appid=None,
            status="none",
            confidence=0.0,
            reason="no_steam_external_game_source",
            candidates=[],
        )

    verified: list[tuple[SteamExternalHit, Any]] = []
    rejected: list[dict[str, Any]] = []
    unverified_any = False

    for hit in ordered:
        check = verifier.check(hit.appid, igdb_name)
        if check.unverified:
            unverified_any = True
            rejected.append({"appid": hit.appid, "reason": "steam_api_unverified"})
            continue
        if not check.available:
            rejected.append({"appid": hit.appid, "reason": check.error or "unavailable"})
            continue
        if is_non_game_steam_type(check.app_type) or (check.app_type and check.app_type != "game"):
            rejected.append({"appid": hit.appid, "reason": f"steam_type_{check.app_type}"})
            continue
        if check.windows is False:
            rejected.append({"appid": hit.appid, "reason": "not_windows"})
            continue
        ok, why = titles_compatible(igdb_name, check.steam_name or "")
        if not ok:
            ok2, why2 = titles_compatible(igdb_name, hit.external_name or "")
            if not ok2:
                rejected.append(
                    {
                        "appid": hit.appid,
                        "reason": f"title_mismatch:{why}",
                        "steam_name": check.steam_name,
                    }
                )
                continue
        verified.append((hit, check))

    if not verified:
        if unverified_any:
            return SteamResolution(
                igdb_game_id=igdb_game_id,
                igdb_name=igdb_name,
                appid=None,
                status="unverified",
                confidence=0.2,
                reason="steam_api_unavailable_for_all_candidates",
                candidates=[h.appid for h in ordered],
                rejected=rejected,
            )
        return SteamResolution(
            igdb_game_id=igdb_game_id,
            igdb_name=igdb_name,
            appid=None,
            status="rejected_non_game",
            confidence=0.9,
            reason="no_verified_steam_game_appid",
            candidates=[h.appid for h in ordered],
            rejected=rejected,
        )

    preferred_because: list[str] = []

    # Unique verified → accept.
    if len(verified) == 1:
        hit, check = verified[0]
        preferred_because.append("single_verified_steam_game")
        return SteamResolution(
            igdb_game_id=igdb_game_id,
            igdb_name=igdb_name,
            appid=hit.appid,
            status="verified",
            confidence=1.0,
            reason="steam_appdetails_verified_type_game_and_title",
            steam_name=check.steam_name,
            steam_type=check.app_type,
            candidates=[h.appid for h in ordered],
            rejected=rejected,
            preferred_because=preferred_because,
        )

    # Exactly one AppID already in Quenly → use that (identity already trusted locally).
    in_catalog = [v for v in verified if v[0].appid in catalog_steam_ids]
    if len(in_catalog) == 1:
        hit, check = in_catalog[0]
        preferred_because.append("unique_match_in_quenly_catalog")
        preferred_because.append(
            f"other_verified_not_in_catalog={[v[0].appid for v in verified if v[0].appid != hit.appid]}"
        )
        return SteamResolution(
            igdb_game_id=igdb_game_id,
            igdb_name=igdb_name,
            appid=hit.appid,
            status="verified",
            confidence=0.92,
            reason="unique_quenly_catalog_steam_appid_among_verified",
            steam_name=check.steam_name,
            steam_type=check.app_type,
            candidates=[h.appid for h in ordered],
            rejected=rejected,
            preferred_because=preferred_because,
            ambiguous_appids=[v[0].appid for v in verified if v[0].appid != hit.appid],
        )

    # Multiple verified, none uniquely decisive → do NOT guess (no lowest-AppID).
    amb = [v[0].appid for v in verified]
    return SteamResolution(
        igdb_game_id=igdb_game_id,
        igdb_name=igdb_name,
        appid=None,
        status="ambiguous_manual_review",
        confidence=0.4,
        reason="multiple_verified_steam_appids_no_unique_signal",
        candidates=[h.appid for h in ordered],
        rejected=rejected,
        preferred_because=["manual_review_required_do_not_guess_appid"],
        ambiguous_appids=amb,
    )


def resolve_many(
    client: IgdbClient,
    games: list[tuple[int, str]],
    verifier: SteamVerifier,
    catalog_steam_ids: set[int] | None = None,
) -> dict[int, SteamResolution]:
    ids = [g for g, _ in games]
    hits_map = fetch_steam_external_hits(client, ids)
    name_map = {g: n for g, n in games}
    return {
        gid: resolve_steam_appid(
            igdb_game_id=gid,
            igdb_name=name_map.get(gid, f"igdb-{gid}"),
            hits=hits_map.get(gid) or [],
            verifier=verifier,
            catalog_steam_ids=catalog_steam_ids,
        )
        for gid in ids
    }
