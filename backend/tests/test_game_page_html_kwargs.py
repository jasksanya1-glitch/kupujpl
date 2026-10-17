"""Ensure game_interactive_html accepts production main.py kwargs (SSR 500 regression)."""
from __future__ import annotations

import inspect

from app.core.game_page_html import game_interactive_html


REQUIRED_KWARGS = {
    "is_free",
    "free_play_url",
    "free_play_label",
    "freshness_note",
    "last_checked_label",
    "worth_buy_enabled",
    "price_confirmed",
    "display_offer_ids",
}


def test_game_interactive_html_accepts_production_kwargs():
    params = inspect.signature(game_interactive_html).parameters
    missing = sorted(REQUIRED_KWARGS - set(params))
    assert not missing, f"missing kwargs: {missing}"


def test_game_interactive_html_renders_with_extra_kwargs():
    html = game_interactive_html(
        title="Hades II",
        slug="hades-ii",
        description="test",
        cover_image=None,
        best_price_pln=117.0,
        best_shop_name="Epic Games",
        is_free=False,
        free_play_url=None,
        free_play_label=None,
        freshness_note="ok",
        last_checked_label="dziś",
        worth_buy_enabled=True,
        price_confirmed=True,
        display_offer_ids=[1, 2],
    )
    assert "Hades II" in html
    assert "theme-cozy-orange" in html or "theme-cozy-orange-app.css" in html
    assert "117" in html
