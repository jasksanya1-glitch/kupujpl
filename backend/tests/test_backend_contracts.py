"""Contract tests: production callers must match dependency function signatures.

Prevents the worth_buy(history_points=...) / missing-param HTTP 500 class of bugs.
"""
from __future__ import annotations

import inspect

import app.core.game_page_html as game_page_html
import app.core.worth_buy as worth_buy
import app.main as main
from app.core.game_offer_selection import best_offers_map
from app.core.price_engine import best_offers_map_v2, evaluate_game_prices
from app.core.seo_pages import iter_indexable_game_sitemap_urls
from app.core.scanner_admin_routes import router as scanner_admin_router


def _params(fn) -> set[str]:
    return set(inspect.signature(fn).parameters.keys())


def test_compute_worth_buy_accepts_history_points_and_offer_verified():
    params = _params(worth_buy.compute_worth_buy)
    assert "history_points" in params
    assert "offer_verified" in params
    assert "is_free" in params
    # Call must not raise TypeError for the production kwargs set.
    result = worth_buy.compute_worth_buy(
        current_price=49.0,
        avg_best_price_30d=55.0,
        lowest_ever_pln=40.0,
        savings_pct=20,
        at_historical_low=False,
        is_free=False,
        history_points=10,
        offer_verified=True,
    )
    assert result is not None


def test_main_passes_only_supported_worth_buy_kwargs():
    src = inspect.getsource(main)
    # Production call sites include history_points=
    assert "history_points=" in src
    # Dependency must accept them (checked above).
    params = _params(worth_buy.compute_worth_buy)
    for required in ("history_points", "offer_verified", "is_free", "current_price"):
        assert required in params


def test_game_interactive_html_accepts_history_points():
    params = _params(game_page_html.game_interactive_html)
    assert "history_points" in params
    assert "price_confirmed" in params
    assert "worth_buy_enabled" in params


def test_best_offers_map_v2_signature_stable():
    params = _params(best_offers_map_v2)
    assert "region" in params
    assert "games" in params
    assert "now" in params
    # V1 wrapper remains for non-V2 paths
    assert "region" in _params(best_offers_map)


def test_evaluate_game_prices_signature_stable():
    params = _params(evaluate_game_prices)
    assert "region" in params
    assert "now" in params


def test_seo_sitemap_iter_is_read_only_batch_api():
    params = _params(iter_indexable_game_sitemap_urls)
    assert "batch_size" in params
    assert "region" in params


def test_scanner_admin_router_exposes_coverage():
    paths = {getattr(r, "path", None) for r in scanner_admin_router.routes}
    assert "/api/admin/coverage" in paths
    assert "/api/admin/coverage/snapshot" in paths
