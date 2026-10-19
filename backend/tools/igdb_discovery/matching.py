"""Match IGDB candidates against local Quenly catalog (read-only).

Primary identity: verified Steam AppID.
Secondary: exact normalized title (never auto-merge remasters/editions).
Fuzzy: manual-review flag only — never auto-merge.
No Steam AppID → quarantine (GOG/Epic later), not rejected.
"""
from __future__ import annotations

import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .fetchers import IgdbCandidate

_EDITION_MARKERS = (
    "deluxe",
    "ultimate",
    "gold edition",
    "complete edition",
    "definitive",
    "premium edition",
    "game of the year",
    "goty",
    "super deluxe",
    "collector",
    "remaster",
    "remastered",
    "remake",
)
_DLC_MARKERS = ("dlc", "expansion", "season pass", "soundtrack", " ost", "bundle", "demo")


def normalize_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", title or "")
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _tokens(title: str) -> set[str]:
    return {t for t in normalize_title(title).split() if len(t) > 1}


def looks_like_edition_or_dlc(name: str) -> bool:
    n = normalize_title(name)
    if any(m in n for m in _DLC_MARKERS):
        return True
    if any(m in n for m in _EDITION_MARKERS):
        return True
    return False


@dataclass
class CatalogHit:
    game_id: int
    title: str
    steam_appid: int | None
    platform: str | None
    steam_app_type: str | None


@dataclass
class MatchResult:
    status: str
    # already_in_catalog | new_candidate | ambiguous | blocked_edition_dlc | quarantine_no_steam
    confidence: float
    reason: str
    matched_game_id: int | None = None
    matched_title: str | None = None
    matched_steam_appid: int | None = None
    match_method: str | None = None  # steam_appid | exact_title | fuzzy_manual_only
    steam_appid_unique_in_catalog: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CatalogStats:
    games_total: int
    with_steam: int
    without_steam: int
    duplicate_steam_appids: int
    without_steam_rows: list[dict[str, Any]]


class CatalogIndex:
    """Read-only index of local games for matching."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.by_steam: dict[int, CatalogHit] = {}
        self.by_norm_title: dict[str, list[CatalogHit]] = {}
        self.steam_counts: dict[int, int] = {}
        self.stats: CatalogStats
        self._load()

    def _load(self) -> None:
        uri = f"file:{self.db_path.as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True)
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, title, steam_appid, platform, steam_app_type FROM games"
        ).fetchall()
        no_steam = [
            dict(r)
            for r in con.execute(
                "SELECT id, title, platform, steam_app_type FROM games WHERE steam_appid IS NULL"
            )
        ]
        dups = con.execute(
            "SELECT steam_appid, COUNT(*) AS c FROM games "
            "WHERE steam_appid IS NOT NULL GROUP BY steam_appid HAVING c > 1"
        ).fetchall()
        con.close()

        for r in rows:
            hit = CatalogHit(
                game_id=int(r["id"]),
                title=str(r["title"]),
                steam_appid=int(r["steam_appid"]) if r["steam_appid"] is not None else None,
                platform=r["platform"],
                steam_app_type=r["steam_app_type"],
            )
            if hit.steam_appid is not None:
                self.by_steam[hit.steam_appid] = hit
                self.steam_counts[hit.steam_appid] = self.steam_counts.get(hit.steam_appid, 0) + 1
            key = normalize_title(hit.title)
            self.by_norm_title.setdefault(key, []).append(hit)

        self.stats = CatalogStats(
            games_total=len(rows),
            with_steam=sum(1 for r in rows if r["steam_appid"] is not None),
            without_steam=len(no_steam),
            duplicate_steam_appids=len(dups),
            without_steam_rows=no_steam,
        )

    def match(self, cand: IgdbCandidate) -> MatchResult:
        unique_flag: bool | None = None
        if cand.steam_appid is not None:
            unique_flag = self.steam_counts.get(cand.steam_appid, 0) <= 1

        # Primary: Steam AppID
        if cand.steam_appid is not None and cand.steam_appid in self.by_steam:
            hit = self.by_steam[cand.steam_appid]
            return MatchResult(
                status="already_in_catalog",
                confidence=1.0,
                reason="steam_appid_exact",
                matched_game_id=hit.game_id,
                matched_title=hit.title,
                matched_steam_appid=hit.steam_appid,
                match_method="steam_appid",
                steam_appid_unique_in_catalog=unique_flag,
            )

        # Secondary: exact normalized title only (no remaster auto-merge).
        key = normalize_title(cand.name)
        exact = self.by_norm_title.get(key) or []
        # If candidate name looks like edition/DLC marker and catalog has base name only — do not merge.
        if len(exact) == 1:
            hit = exact[0]
            # Guard: different steam ids → ambiguous, never merge.
            if (
                cand.steam_appid
                and hit.steam_appid
                and int(cand.steam_appid) != int(hit.steam_appid)
            ):
                return MatchResult(
                    status="ambiguous",
                    confidence=0.5,
                    reason="same_title_different_steam_appid",
                    matched_game_id=hit.game_id,
                    matched_title=hit.title,
                    matched_steam_appid=hit.steam_appid,
                    match_method="exact_title",
                    steam_appid_unique_in_catalog=unique_flag,
                )
            return MatchResult(
                status="already_in_catalog",
                confidence=0.92,
                reason="exact_normalized_title",
                matched_game_id=hit.game_id,
                matched_title=hit.title,
                matched_steam_appid=hit.steam_appid,
                match_method="exact_title",
                steam_appid_unique_in_catalog=unique_flag,
            )
        if len(exact) > 1:
            return MatchResult(
                status="ambiguous",
                confidence=0.4,
                reason=f"multiple_exact_title_hits:{len(exact)}",
                matched_title=exact[0].title,
                match_method="exact_title",
                steam_appid_unique_in_catalog=unique_flag,
            )

        # Fuzzy: manual review only — never already_in_catalog.
        q = _tokens(cand.name)
        if len(q) >= 2:
            best: tuple[float, CatalogHit] | None = None
            for hits in self.by_norm_title.values():
                for hit in hits:
                    t = _tokens(hit.title)
                    if not t:
                        continue
                    # Skip if edition token sets differ.
                    edition = {
                        "deluxe",
                        "ultimate",
                        "remaster",
                        "remastered",
                        "remake",
                        "goty",
                        "dlc",
                        "soundtrack",
                    }
                    if ((q - t) | (t - q)) & edition:
                        continue
                    overlap = len(q & t) / max(len(q | t), 1)
                    if overlap >= 0.88 and (best is None or overlap > best[0]):
                        best = (overlap, hit)
            if best and best[0] >= 0.92:
                hit = best[1]
                return MatchResult(
                    status="ambiguous",
                    confidence=best[0],
                    reason="fuzzy_title_manual_review_only",
                    matched_game_id=hit.game_id,
                    matched_title=hit.title,
                    matched_steam_appid=hit.steam_appid,
                    match_method="fuzzy_manual_only",
                    steam_appid_unique_in_catalog=unique_flag,
                )

        if not cand.steam_appid:
            return MatchResult(
                status="quarantine_no_steam",
                confidence=0.3,
                reason="no_steam_appid_quarantine",
                match_method=None,
                steam_appid_unique_in_catalog=None,
            )

        # Related edition/remaster in catalog (different Steam AppID) → manual review,
        # never auto-merge.
        related = self._related_edition_hit(cand.name)
        if related is not None:
            return MatchResult(
                status="ambiguous",
                confidence=0.55,
                reason="related_edition_or_remaster_in_catalog_manual_review",
                matched_game_id=related.game_id,
                matched_title=related.title,
                matched_steam_appid=related.steam_appid,
                match_method="fuzzy_manual_only",
                steam_appid_unique_in_catalog=unique_flag,
            )

        return MatchResult(
            status="new_candidate",
            confidence=0.85,
            reason="steam_appid_absent_from_catalog",
            match_method="steam_appid",
            steam_appid_unique_in_catalog=unique_flag,
        )

    def _related_edition_hit(self, name: str) -> CatalogHit | None:
        q = _tokens(name)
        if len(q) < 2:
            return None
        edition = {
            "deluxe",
            "ultimate",
            "remaster",
            "remastered",
            "remake",
            "goty",
            "director",
            "directors",
            "cut",
            "complete",
            "definitive",
            "enhanced",
            "anniversary",
            "edition",
        }
        q_core = q - edition
        if len(q_core) < 2:
            return None
        best: tuple[float, CatalogHit] | None = None
        for hits in self.by_norm_title.values():
            for hit in hits:
                t = _tokens(hit.title)
                t_core = t - edition
                if not t_core:
                    continue
                # Core tokens nearly equal but full token sets differ via edition words.
                if q_core != t_core and not (q_core <= t_core or t_core <= q_core):
                    continue
                if q_core == t_core or q_core <= t_core or t_core <= q_core:
                    if (q - t) or (t - q):
                        overlap = len(q_core & t_core) / max(len(q_core | t_core), 1)
                        if overlap >= 0.9 and (best is None or overlap > best[0]):
                            best = (overlap, hit)
        return best[1] if best else None
