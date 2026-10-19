"""Steam Store appdetails checks — read-only, independent of production scanners."""
from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

import requests

from . import config

logger = logging.getLogger("igdb_discovery.steam_verify")

APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
_NON_GAME_TYPES = frozenset(
    {
        "dlc",
        "demo",
        "music",
        "video",
        "mod",
        "hardware",
        "advertising",
        "series",
        "episode",
        "software",
        "config",
        "tool",
    }
)
_NAME_JUNK = re.compile(r"[^\w\s]", re.UNICODE)


def _norm(s: str) -> str:
    text = unicodedata.normalize("NFKD", s or "")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = _NAME_JUNK.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def titles_compatible(igdb_name: str, steam_name: str) -> tuple[bool, str]:
    """Strict-ish title compatibility — no fuzzy merge of remasters/editions."""
    a, b = _norm(igdb_name), _norm(steam_name)
    if not a or not b:
        return False, "empty_title"
    if a == b:
        return True, "exact"
    # Allow trailing platform tags Steam sometimes adds.
    for suffix in (" pc", " windows", " steam"):
        if a + suffix == b or b + suffix == a:
            return True, "platform_suffix"
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return False, "empty_tokens"
    # Reject if one side has edition tokens the other lacks.
    edition = {
        "deluxe",
        "ultimate",
        "goty",
        "definitive",
        "remaster",
        "remastered",
        "remake",
        "complete",
        "gold",
        "premium",
        "anniversary",
        "enhanced",
        "dlc",
        "soundtrack",
        "demo",
    }
    extra_a = (ta - tb) & edition
    extra_b = (tb - ta) & edition
    if extra_a or extra_b:
        return False, f"edition_token_diff:{sorted(extra_a | extra_b)}"
    # Containment of shorter in longer when token overlap is high.
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if shorter in longer and len(ta & tb) >= max(1, min(len(ta), len(tb)) - 1):
        return True, "containment"
    overlap = len(ta & tb) / max(len(ta | tb), 1)
    if overlap >= 0.9:
        return True, f"high_overlap:{overlap:.2f}"
    return False, f"title_mismatch:overlap={overlap:.2f}"


@dataclass
class SteamCheck:
    steam_appid: int
    available: bool
    unverified: bool  # True when Steam API unavailable / rate-limited
    steam_name: str | None = None
    app_type: str | None = None  # game, dlc, demo, …
    is_free: bool | None = None
    coming_soon: bool | None = None
    release_date: str | None = None
    windows: bool | None = None
    title_ok: bool | None = None
    title_reason: str | None = None
    recommendations: int | None = None
    error: str | None = None
    raw_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SteamVerifier:
    def __init__(self, *, pause_sec: float | None = None) -> None:
        self.pause = pause_sec if pause_sec is not None else float(
            __import__("os").environ.get("IGDB_STEAM_PAUSE_SEC", "1.05")
        )
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": config.USER_AGENT})
        self._last = 0.0
        self._cache: dict[int, dict[str, Any] | None] = {}

    def _throttle(self) -> None:
        gap = time.time() - self._last
        if gap < self.pause:
            time.sleep(self.pause - gap)

    def fetch_details(self, appid: int) -> dict[str, Any] | None:
        if appid in self._cache:
            return self._cache[appid]
        self._throttle()
        try:
            resp = self._session.get(
                APPDETAILS_URL,
                params={"appids": appid, "cc": "pl", "l": "english"},
                timeout=25,
            )
            self._last = time.time()
            if resp.status_code == 429:
                logger.warning("Steam 429 for appid=%s", appid)
                self._cache[appid] = None
                return None
            if resp.status_code != 200:
                self._cache[appid] = None
                return None
            block = resp.json().get(str(appid))
            if not block or not block.get("success"):
                self._cache[appid] = {}  # exists as miss
                return {}
            data = block.get("data") or {}
            self._cache[appid] = data
            return data
        except Exception as exc:  # noqa: BLE001
            logger.warning("Steam appdetails failed appid=%s: %s", appid, exc)
            self._cache[appid] = None
            return None

    def check(self, appid: int | None, igdb_name: str) -> SteamCheck:
        if not appid:
            return SteamCheck(
                steam_appid=0,
                available=False,
                unverified=False,
                error="missing_steam_appid",
            )
        data = self.fetch_details(int(appid))
        if data is None:
            return SteamCheck(
                steam_appid=int(appid),
                available=False,
                unverified=True,
                error="steam_api_unavailable",
            )
        if data == {}:
            return SteamCheck(
                steam_appid=int(appid),
                available=False,
                unverified=False,
                error="steam_app_not_found_or_region_blocked",
            )

        steam_name = str(data.get("name") or "")
        app_type = str(data.get("type") or "").lower() or None
        is_free = bool(data.get("is_free")) if "is_free" in data else None
        rel = data.get("release_date") or {}
        coming_soon = bool(rel.get("coming_soon")) if isinstance(rel, dict) else None
        release_date = rel.get("date") if isinstance(rel, dict) else None
        platforms = data.get("platforms") or {}
        windows = bool(platforms.get("windows")) if isinstance(platforms, dict) else None
        title_ok, title_reason = titles_compatible(igdb_name, steam_name)
        recs = None
        if isinstance(data.get("recommendations"), dict):
            try:
                recs = int(data["recommendations"].get("total") or 0)
            except (TypeError, ValueError):
                recs = None

        return SteamCheck(
            steam_appid=int(appid),
            available=True,
            unverified=False,
            steam_name=steam_name,
            app_type=app_type,
            is_free=is_free,
            coming_soon=coming_soon,
            release_date=release_date,
            windows=windows,
            title_ok=title_ok,
            title_reason=title_reason,
            recommendations=recs,
            raw_type=app_type,
        )


def is_non_game_steam_type(app_type: str | None) -> bool:
    return bool(app_type and app_type in _NON_GAME_TYPES)
