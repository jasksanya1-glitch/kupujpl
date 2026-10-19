"""One-shot local catalog audit for IGDB Game Discovery prototype (read-only)."""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "database.db"
OUT = Path(__file__).resolve().parent / "reports" / "audit_local.json"


def main() -> None:
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    games = con.execute("SELECT COUNT(*) AS n FROM games").fetchone()["n"]
    with_steam = con.execute(
        "SELECT COUNT(*) AS n FROM games WHERE steam_appid IS NOT NULL"
    ).fetchone()["n"]
    by_platform = dict(
        con.execute(
            "SELECT COALESCE(platform,'?') AS p, COUNT(*) FROM games GROUP BY platform"
        ).fetchall()
    )
    enriched = con.execute(
        "SELECT COUNT(*) AS n FROM games WHERE steam_enriched = 1"
    ).fetchone()["n"]
    offers = con.execute("SELECT COUNT(*) AS n FROM offers").fetchone()["n"]
    shops = [
        dict(r)
        for r in con.execute(
            "SELECT shop_name, COUNT(*) AS n FROM offers GROUP BY shop_name ORDER BY n DESC LIMIT 20"
        )
    ]
    app_types = dict(
        con.execute(
            "SELECT COALESCE(steam_app_type,'null') AS t, COUNT(*) FROM games "
            "GROUP BY steam_app_type ORDER BY COUNT(*) DESC"
        ).fetchall()
    )
    dup_titles = con.execute(
        "SELECT LOWER(title) AS t, COUNT(*) AS n FROM games GROUP BY LOWER(title) "
        "HAVING n > 1 ORDER BY n DESC LIMIT 15"
    ).fetchall()
    sample = [
        dict(r)
        for r in con.execute(
            "SELECT id, title, steam_appid, platform, steam_app_type, steam_enriched "
            "FROM games WHERE steam_appid IS NOT NULL ORDER BY id LIMIT 8"
        )
    ]
    report = {
        "db_path": str(DB),
        "games_total": games,
        "games_with_steam_appid": with_steam,
        "games_enriched": enriched,
        "by_platform": by_platform,
        "steam_app_type_counts": app_types,
        "offers_total": offers,
        "top_shops": shops,
        "duplicate_title_examples": [dict(r) for r in dup_titles],
        "sample_games": sample,
        "notes": [
            "Game table has unique steam_appid; no igdb_id column yet.",
            "DiscoverCandidate is deal-staging, not new-title staging.",
            "Catalog ingest today: steam_catalog.upsert_game_stub + Tier A top sellers.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    con.close()


if __name__ == "__main__":
    main()
