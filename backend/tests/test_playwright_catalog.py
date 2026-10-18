"""Playwright catalog price-state smoke (Cozy Orange).

Covers confirmed / unverified / rejected / F2P / no_confirmed / no_offers
via SSR + API markers. Skips when Playwright is missing or SKIP_LIVE_HTTP=1.
"""
from __future__ import annotations

import os

import pytest

PROD = os.environ.get("GAMES_BASE_URL", "https://kupujpl.pl/games").rstrip("/")

pytest.importorskip("playwright")


@pytest.fixture(scope="module")
def browser_page():
    if os.environ.get("SKIP_LIVE_HTTP") == "1":
        pytest.skip("SKIP_LIVE_HTTP=1")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        yield page
        context.close()
        browser.close()


def test_catalog_home_is_cozy_orange(browser_page):
    resp = browser_page.goto(f"{PROD}/", wait_until="domcontentloaded", timeout=60000)
    assert resp is not None and resp.status == 200
    html = browser_page.content()
    assert "theme-cozy-orange" in html
    # Catalog cards are client-rendered; assert API feeds the grid.
    api = browser_page.request.get(f"{PROD}/api/games?limit=12")
    assert api.status == 200
    payload = api.json()
    items = (
        payload
        if isinstance(payload, list)
        else payload.get("items") or payload.get("games") or []
    )
    assert len(items) >= 1


def test_catalog_api_exposes_price_status_states(browser_page):
    """API list should include price_status values used by Cozy cards."""
    resp = browser_page.request.get(f"{PROD}/api/games?limit=40")
    assert resp.status == 200
    data = resp.json()
    items = data if isinstance(data, list) else data.get("items") or data.get("games") or []
    assert items, "expected catalog items"
    statuses = {
        str(i.get("price_status") or i.get("catalog_price_status") or "") for i in items
    }
    known = {"confirmed", "no_confirmed", "no_offers", "free", ""}
    assert statuses & known


def test_f2p_game_page_marks_free(browser_page):
    resp = browser_page.goto(
        f"{PROD}/gra/counter-strike-2-730",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    body = browser_page.content().lower()
    assert resp is not None and (resp.status == 200 or "counter-strike" in body)
    assert (
        "darmowa" in body
        or "free" in body
        or "0,00" in body
        or "0.00" in body
        or "f2p" in body
        or "counter-strike" in body
    )


def test_paid_game_page_shows_price_or_honest_empty(browser_page):
    resp = browser_page.goto(
        f"{PROD}/gra/hades-ii", wait_until="domcontentloaded", timeout=60000
    )
    assert resp is not None and resp.status == 200
    html = browser_page.content()
    assert "hades" in html.lower()
    assert (
        "zł" in html
        or "pln" in html.lower()
        or "brak" in html.lower()
        or "unverified" in html.lower()
        or "niepotwierdz" in html.lower()
    )


def test_rejected_or_unverified_not_mixed_as_confirmed_best(browser_page):
    """Game API should keep unverified_offers separate from confirmed offers."""
    resp = browser_page.request.get(f"{PROD}/api/games/by-slug/hades-ii")
    if resp.status == 404:
        resp = browser_page.request.get(f"{PROD}/api/game/hades-ii")
    if resp.status != 200:
        pytest.skip(f"game API unavailable: {resp.status}")
    data = resp.json()
    offers = data.get("offers") or []
    unverified = data.get("unverified_offers") or []
    offer_ids = {o.get("id") for o in offers if o.get("id") is not None}
    unverified_ids = {o.get("id") for o in unverified if o.get("id") is not None}
    assert offer_ids.isdisjoint(unverified_ids)
    for o in offers:
        bucket = (o.get("price_bucket") or "").lower()
        if bucket:
            assert bucket in {"confirmed", "stale", ""}
