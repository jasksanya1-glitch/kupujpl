"""Official Steam IStoreService/GetAppList integration (optional).

Requires STEAM_WEB_API_KEY. Without the key this module documents the gap and
does not scrape or call deprecated ISteamApps/GetAppList/v2 as a primary source.
Isolated local SQLite cache only — never production.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from . import config

logger = logging.getLogger("igdb_discovery.steam_istore")

ISTORE_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
CACHE_DB = config.STAGING_DIR / "steam_istore_cache.sqlite3"


@dataclass
class IStoreCredentialReport:
    key_present: bool
    env_var: str
    ready: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def credential_report() -> IStoreCredentialReport:
    key = (os.environ.get("STEAM_WEB_API_KEY") or "").strip()
    if not key:
        return IStoreCredentialReport(
            key_present=False,
            env_var="STEAM_WEB_API_KEY",
            ready=False,
            message=(
                "STEAM_WEB_API_KEY missing. Add it to backend/.env to enable "
                "IStoreService/GetAppList pagination (include_games=1, no DLC/software). "
                "Do not paste the key into chat. Deprecated ISteamApps/GetAppList/v2 "
                "is not used as the primary mechanism."
            ),
        )
    return IStoreCredentialReport(
        key_present=True,
        env_var="STEAM_WEB_API_KEY",
        ready=True,
        message="STEAM_WEB_API_KEY present — IStore sync available.",
    )


def _init_cache(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS istore_apps (
              appid INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              last_seen_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS istore_meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )


def sync_istore_games(*, max_pages: int = 200, incremental: bool = True) -> dict[str, Any]:
    """Paginated games-only sync into isolated cache. No production writes.

    AppID is identity only — never treat membership as a popularity signal.
    Without STEAM_WEB_API_KEY returns ok=False (unknown), does not scrape.
    """
    report = credential_report()
    if not report.ready:
        return {
            "ok": False,
            "credential": report.to_dict(),
            "apps": 0,
            "status": "unknown",
            "reason": "STEAM_WEB_API_KEY_missing",
        }

    api_key = (os.environ.get("STEAM_WEB_API_KEY") or "").strip()
    _init_cache(CACHE_DB)
    session = requests.Session()
    session.headers.update({"User-Agent": config.USER_AGENT})

    last_appid = 0
    if incremental and CACHE_DB.is_file():
        with sqlite3.connect(CACHE_DB) as con:
            row = con.execute("SELECT MAX(appid) FROM istore_apps").fetchone()
            if row and row[0] is not None:
                last_appid = int(row[0])
    total = 0
    pages = 0
    now = datetime.now(timezone.utc).isoformat()

    with sqlite3.connect(CACHE_DB) as con:
        while pages < max_pages:
            resp = session.get(
                ISTORE_URL,
                params={
                    "key": api_key,
                    "include_games": 1,
                    "include_dlc": 0,
                    "include_software": 0,
                    "include_videos": 0,
                    "include_hardware": 0,
                    "max_results": 50000,
                    "last_appid": last_appid,
                },
                timeout=90,
            )
            if resp.status_code == 403:
                return {
                    "ok": False,
                    "credential": report.to_dict(),
                    "error": "steam_istore_forbidden",
                    "apps": total,
                }
            resp.raise_for_status()
            apps = (resp.json().get("response") or {}).get("apps") or []
            if not apps:
                break
            for app in apps:
                appid = int(app["appid"])
                name = (app.get("name") or "").strip() or f"app-{appid}"
                con.execute(
                    "INSERT INTO istore_apps(appid,name,last_seen_at) VALUES(?,?,?) "
                    "ON CONFLICT(appid) DO UPDATE SET name=excluded.name, last_seen_at=excluded.last_seen_at",
                    (appid, name, now),
                )
                total += 1
            last_appid = int(apps[-1]["appid"])
            pages += 1
            if len(apps) < 50000:
                break
            time.sleep(0.45)
        con.execute(
            "INSERT INTO istore_meta(key,value) VALUES('last_sync',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (
                json.dumps(
                    {
                        "at": now,
                        "apps_upserted": total,
                        "pages": pages,
                        "incremental": incremental,
                        "resume_last_appid": last_appid,
                    }
                ),
            ),
        )

    return {
        "ok": True,
        "credential": report.to_dict(),
        "apps_upserted": total,
        "pages": pages,
        "incremental": incremental,
        "cache_db": str(CACHE_DB),
        "note": "IStore is an identity catalog, not a demand ranking.",
    }


def istore_has_appid(appid: int) -> bool | None:
    """None = cache unavailable; True/False = membership."""
    if not CACHE_DB.is_file():
        return None
    with sqlite3.connect(CACHE_DB) as con:
        row = con.execute("SELECT 1 FROM istore_apps WHERE appid=?", (int(appid),)).fetchone()
    return bool(row)
