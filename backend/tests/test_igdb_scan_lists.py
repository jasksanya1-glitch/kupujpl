"""IGDB scan lists → scanner priority cache."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.core import igdb_scan_lists


@pytest.fixture
def lists_cache_tmp(monkeypatch, tmp_path):
    cache = tmp_path / "igdb_scan_lists.json"
    monkeypatch.setattr(igdb_scan_lists, "LISTS_CACHE", cache)
    return cache


def test_refresh_skipped_without_flags(monkeypatch, lists_cache_tmp):
    monkeypatch.setattr(igdb_scan_lists, "credentials_from_env", lambda: ("id", "sec"))
    monkeypatch.setattr(igdb_scan_lists, "_write_production_enabled", lambda: False)
    monkeypatch.setattr(igdb_scan_lists, "enqueue_scanners_enabled", lambda: False)
    out = igdb_scan_lists.refresh_igdb_scan_lists(MagicMock())
    assert out.get("skipped") is True


def test_priority_rank_map(lists_cache_tmp):
    lists_cache_tmp.write_text(
        json.dumps(
            {
                "lists": {
                    "TRENDING": [{"game_id": 10, "rank": 1}],
                    "POPULAR": [{"game_id": 20, "rank": 1}],
                },
                "enqueued_game_ids": [10, 20],
            }
        ),
        encoding="utf-8",
    )
    rank = igdb_scan_lists.igdb_scan_priority_rank_map()
    assert rank[10] == 0
    assert rank[20] == 1
    assert igdb_scan_lists.igdb_scan_priority_game_ids() == {10, 20}
