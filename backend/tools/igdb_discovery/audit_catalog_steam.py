"""Read-only audit: Quenly Steam AppIDs that conflict with IGDB Steam links.

Never writes production. Reports suspicious multi-AppID IGDB mappings where
Quenly stores a non-canonical AppID.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import config
from .client import IgdbClient
from .steam_resolve import fetch_steam_external_hits
from .steam_verify import SteamVerifier, titles_compatible


def audit(*, sample_limit: int = 80) -> dict:
    if not config.CATALOG_DB.is_file():
        raise FileNotFoundError(config.CATALOG_DB)
    con = sqlite3.connect(f"file:{config.CATALOG_DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, title, steam_appid FROM games "
        "WHERE steam_appid IS NOT NULL AND platform='pc' "
        "ORDER BY steam_review_count DESC NULLS LAST LIMIT ?",
        (sample_limit,),
    ).fetchall()
    con.close()

    client = IgdbClient()
    client.ensure_token()
    verifier = SteamVerifier()
    suspicious: list[dict] = []

    for row in rows:
        title = row["title"]
        appid = int(row["steam_appid"])
        # Search IGDB by name (bounded).
        found = client.query(
            "games",
            f'fields id,name; search "{title.replace(chr(34), "")[:80]}"; limit 3;',
        )
        if not found:
            continue
        gid = int(found[0]["id"])
        hits = fetch_steam_external_hits(client, [gid]).get(gid) or []
        appids = sorted({h.appid for h in hits})
        if len(appids) <= 1:
            continue
        if appid not in appids:
            continue
        # If Quenly has a higher AppID while a lower verified twin exists → flag.
        lower = [a for a in appids if a < appid]
        if not lower:
            continue
        # Verify both names
        check_cur = verifier.check(appid, title)
        check_low = verifier.check(lower[0], title)
        if not (check_cur.available and check_low.available):
            continue
        ok1, _ = titles_compatible(title, check_cur.steam_name or "")
        ok2, _ = titles_compatible(title, check_low.steam_name or "")
        if ok1 and ok2 and check_cur.app_type == "game" and check_low.app_type == "game":
            suspicious.append(
                {
                    "quenly_id": row["id"],
                    "title": title,
                    "quenly_steam_appid": appid,
                    "igdb_id": gid,
                    "igdb_steam_appids": appids,
                    "suggested_canonical": min(appids),
                    "note": "multiple_verified_steam_listings_same_title",
                }
            )

    report = {
        "sampled": len(rows),
        "suspicious_count": len(suspicious),
        "suspicious": suspicious,
        "production_changed": False,
    }
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.REPORTS_DIR / "catalog_steam_appid_audit.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(audit(sample_limit=40), ensure_ascii=False, indent=2))
