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


def test_merge_prepends_scan_lists(monkeypatch):
    scan_payload = {
        "updated_at": "2026-10-20T12:00:00+00:00",
        "lists": {
            "NEW_RELEASES": [
                {"steam_appid": 1203620, "name": "Enshrouded", "game_id": 1},
            ],
            "TRENDING": [
                {"steam_appid": 1326470, "name": "Silksong", "game_id": 2},
            ],
            "RECENT_HITS": [],
            "UPCOMING": [],
            "POPULAR": [{"steam_appid": 730, "name": "CS2", "game_id": 3}],
        },
    }
    monkeypatch.setattr(igdb_home, "load_igdb_scan_lists_cache", lambda: scan_payload)
    monkeypatch.setattr(igdb_home, "home_sections_enabled", lambda: True)
    steam = {"updated_at": "2026-10-18", "sections": [{"slug": "top", "games": []}]}
    merged = igdb_home.merge_home_section_caches(steam)
    assert merged is not None
    slugs = [s["slug"] for s in merged["sections"]]
    assert slugs[0] == "nowe-premiery"
    assert slugs[1] == "trending"
    assert "popularne" not in slugs
    assert merged["sections"][0]["games"][0]["appid"] == 1203620
    assert merged["sections"][1]["slug"] == "trending"
    assert merged["sections"][-1]["slug"] == "top"


def test_build_home_sections_uses_scan_list_cover():
    hashed = (
        "https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/"
        "3764200/ce5437442768e38eb575f205ab9397d0264017b0/header.jpg"
    )
    scan_payload = {
        "updated_at": "2026-10-20T12:00:00+00:00",
        "lists": {
            "NEW_RELEASES": [],
            "TRENDING": [
                {
                    "steam_appid": 3764200,
                    "name": "Resident Evil Requiem",
                    "cover_image": hashed,
                },
            ],
            "RECENT_HITS": [],
            "UPCOMING": [],
            "POPULAR": [],
        },
    }
    out = igdb_home.build_home_sections_from_scan_lists(scan_payload)
    assert out is not None
    assert out["sections"][0]["slug"] == "trending"
    cover = out["sections"][0]["games"][0]["cover_image"]
    assert "ce5437442768e38eb575f205ab9397d0264017b0" in cover


def test_home_section_list_keys_env(monkeypatch):
    monkeypatch.setenv("IGDB_HOME_SECTION_LISTS", "TRENDING,POPULAR")
    assert igdb_home.home_section_list_keys() == ("TRENDING", "POPULAR")


def test_igdb_scan_home_shows_missing_db_and_no_offers():
    assert not igdb_home.is_hidden_from_igdb_scan_home_section(
        None,
        section_slug="nowe-premiery",
        item={"appid": 1203620, "title": "Enshrouded"},
    )
    stub = type(
        "G",
        (),
        {
            "steam_app_type": None,
            "is_free": False,
            "is_coming_soon": False,
            "steam_review_count": None,
            "steam_review_positive_pct": None,
        },
    )()
    assert not igdb_home.is_hidden_from_igdb_scan_home_section(
        stub,
        section_slug="trending",
        item={"appid": 1, "title": "Trend Stub"},
    )


def test_igdb_scan_nowe_premiery_keeps_coming_soon_stub():
    coming = type(
        "G",
        (),
        {
            "steam_app_type": None,
            "is_free": False,
            "is_coming_soon": True,
            "steam_review_count": None,
            "steam_review_positive_pct": None,
        },
    )()
    assert not igdb_home.is_hidden_from_igdb_scan_home_section(
        coming,
        section_slug="nowe-premiery",
        item={"appid": 1, "title": "Fresh Release"},
    )


def test_igdb_scan_nadchodzace_keeps_coming_soon():
    coming = type(
        "G",
        (),
        {
            "steam_app_type": None,
            "is_free": False,
            "is_coming_soon": True,
            "steam_review_count": None,
            "steam_review_positive_pct": None,
        },
    )()
    assert not igdb_home.is_hidden_from_igdb_scan_home_section(
        coming,
        section_slug="nadchodzace",
        item={"appid": 99, "title": "Future Game"},
    )
