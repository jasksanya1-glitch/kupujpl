"""IGDB homepage sections — cache refresh with mocked IGDB API."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core import igdb_home
from app.core.igdb_home import refresh_igdb_home_cache


@pytest.fixture
def igdb_cache_tmp(monkeypatch, tmp_path):
    cache = tmp_path / "igdb_home_cache.json"
    monkeypatch.setattr(igdb_home, "CACHE_FILE", cache)
    return cache


def test_refresh_skips_without_credentials(monkeypatch, igdb_cache_tmp):
    monkeypatch.setattr(igdb_home, "credentials_from_env", lambda: None)
    db = MagicMock()
    out = refresh_igdb_home_cache(db)
    assert out.get("skipped") is True
    assert not igdb_cache_tmp.is_file()


def test_refresh_writes_trending_section(monkeypatch, igdb_cache_tmp):
    monkeypatch.setattr(igdb_home, "credentials_from_env", lambda: ("id", "secret"))

    want_pairs = [(101, 50.0), (102, 40.0)]
    seller_pairs = [(201, 90.0)]

    hydrated = {
        101: {
            "id": 101,
            "name": "Trend Game",
            "platforms": [6],
            "game_type": 0,
        },
        102: {
            "id": 102,
            "name": "Other",
            "platforms": [6],
            "game_type": 0,
        },
        201: {
            "id": 201,
            "name": "Popular Game",
            "platforms": [6],
            "game_type": 0,
        },
    }

    def fake_pop(client, pop_type, *, limit):  # noqa: ANN001, ARG001
        if pop_type == igdb_home.POP_WANT_TO_PLAY:
            return want_pairs
        if pop_type == igdb_home.POP_GLOBAL_TOP_SELLERS:
            return seller_pairs
        return []

    monkeypatch.setattr(igdb_home, "_fetch_pop_pairs", fake_pop)
    monkeypatch.setattr(igdb_home, "_hydrate_games", lambda _c, ids: {i: hydrated[i] for i in ids if i in hydrated})
    monkeypatch.setattr(igdb_home, "_is_pc_mainline", lambda _raw: True)
    monkeypatch.setattr(
        igdb_home,
        "_resolve_steam_appids",
        lambda _c, games, _catalog: {gid: 5000 + gid for gid, _ in games},
    )
    monkeypatch.setattr(igdb_home, "_upsert_section_games", lambda _db, _items: None)
    monkeypatch.setattr(igdb_home, "_enrich_cache_items", lambda _db, items: items)

    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    out = refresh_igdb_home_cache(db, games_per_section=2)
    assert out.get("skipped") is not True
    assert igdb_cache_tmp.is_file()
    data = json.loads(igdb_cache_tmp.read_text(encoding="utf-8"))
    slugs = [s["slug"] for s in data["sections"]]
    assert slugs[0] == "igdb-trending"
    assert "igdb-popular" in slugs
    trending = data["sections"][0]
    assert trending["games"][0]["appid"] == 5101


def test_merge_prepends_igdb(monkeypatch, tmp_path):
    igdb_file = tmp_path / "igdb.json"
    igdb_file.write_text(
        json.dumps(
            {
                "updated_at": "2026-10-19T12:00:00+00:00",
                "sections": [{"slug": "igdb-trending", "games": [{"appid": 1}]}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(igdb_home, "CACHE_FILE", igdb_file)
    steam = {"updated_at": "2026-10-18", "sections": [{"slug": "top", "games": []}]}
    merged = igdb_home.merge_home_section_caches(steam)
    assert merged is not None
    assert merged["sections"][0]["slug"] == "igdb-trending"
    assert merged["sections"][1]["slug"] == "top"
