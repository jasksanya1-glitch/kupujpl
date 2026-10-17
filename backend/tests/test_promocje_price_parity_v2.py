"""Promocje / SEO landings must not surface rejected wrong-SKU prices (PE V2)."""
from __future__ import annotations

import pytest

from app.core.game_offer_selection import best_offers_map
from app.core.price_engine import evaluate_game_prices_from_db, offer_row_display_tier
from app.core.seo_landings import SeoLanding, collect_landing_items
from app.core.seo_pages import deals_landing_html
from app.models.models import Game, Offer
from app.schemas.schemas import GameListResponse


@pytest.fixture(autouse=True)
def _force_pe_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRICE_ENGINE_V2", "1")


def _game(db, **kwargs) -> Game:
    n = db.query(Game).count() + 1
    defaults = dict(
        title=f"Game {n}",
        slug=f"game-{n}",
        steam_appid=800000 + n,
        is_free=False,
        steam_app_type="game",
        platform="pc",
        steam_enriched=True,
        steam_review_count=8000,
        steam_review_positive_pct=88.0,
        steam_recommendations=3000,
    )
    defaults.update(kwargs)
    g = Game(**defaults)
    db.add(g)
    db.flush()
    return g


def _offer(db, game: Game, shop: str, price: float, **kwargs) -> Offer:
    defaults = dict(
        game_id=game.id,
        shop_name=shop,
        price_pln=price,
        in_stock=True,
        is_official=shop in {"Steam", "GOG", "Epic Games"},
        match_confidence=1.0 if shop not in {"Steam", "GOG", "Epic Games"} else None,
        affiliate_url=f"https://example.com/{shop.lower().replace(' ', '')}/{game.slug}",
        activation_region="global",
    )
    defaults.update(kwargs)
    o = Offer(**defaults)
    db.add(o)
    db.flush()
    return o


def _build_item(game: Game, best: Offer | None, steam: Offer | None) -> GameListResponse:
    steam_price = float(steam.price_pln) if steam and steam.price_pln else None
    best_price = float(best.price_pln) if best and best.price_pln else None
    savings_pct = None
    if steam_price and best_price and best_price < steam_price:
        savings_pct = int(round(((steam_price - best_price) / steam_price) * 100))
    return GameListResponse(
        id=game.id,
        title=game.title,
        slug=game.slug,
        cover_image=None,
        steam_appid=game.steam_appid,
        platform="pc",
        best_price_pln=best_price,
        best_shop_name=best.shop_name if best else None,
        best_price_is_official=bool(best.is_official) if best else None,
        steam_price_pln=steam_price,
        savings_pct=savings_pct,
    )


def test_promocje_rejects_gog_dawn_of_war_as_rogue_trader(db) -> None:
    """Wrong-SKU GOG Dawn of War @ 8.99 must never be promocje best for Rogue Trader."""
    g = _game(
        db,
        title="Warhammer 40,000: Rogue Trader",
        slug="warhammer-40000-rogue-trader-2186680",
        steam_appid=2186680,
    )
    _offer(db, g, "Steam", 199.99, is_official=True)
    _offer(
        db,
        g,
        "Epic Games",
        199.99,
        is_official=True,
        affiliate_url="https://store.epicgames.com/pl/p/warhammer-40000-rogue-trader",
    )
    wrong = _offer(
        db,
        g,
        "GOG",
        8.99,
        is_official=True,
        affiliate_url=(
            "https://www.gog.com/pl/game/warhammer_40000_dawn_of_war_anniversary_edition"
        ),
        match_confidence=0.675,
    )

    result = evaluate_game_prices_from_db(db, g, region="pl")
    wrong_row = next(r for r in result.rows if r.offer and r.offer.id == wrong.id)
    assert offer_row_display_tier(wrong_row) == "rejected"
    assert result.best_confirmed_offer is not None
    assert float(result.best_confirmed_offer.price_pln) == pytest.approx(199.99)
    assert result.best_confirmed_offer.shop_name == "Epic Games"

    quality = best_offers_map(db, [g.id], region="pl")
    assert float(quality[g.id].price_pln) == pytest.approx(199.99)
    assert quality[g.id].shop_name == "Epic Games"

    landing = SeoLanding("promocje", "promocje", "Promocje", "inne", min_savings_pct=5)
    items = collect_landing_items(db, landing, build_item=_build_item, limit=60)
    by_slug = {i.slug: i for i in items}
    # Equal Steam/Epic → no savings → must not appear as a “promo”
    assert "warhammer-40000-rogue-trader-2186680" not in by_slug

    # If a real cheaper verified keyshop existed, price must still not be 8.99
    _offer(
        db,
        g,
        "Fanatical",
        149.99,
        is_official=False,
        match_confidence=1.4,
        affiliate_url="https://www.fanatical.com/en/game/warhammer-40000-rogue-trader",
    )
    items2 = collect_landing_items(db, landing, build_item=_build_item, limit=60)
    hit = next((i for i in items2 if i.slug == g.slug), None)
    if hit is not None:
        assert hit.best_price_pln != pytest.approx(8.99)
        assert hit.best_shop_name != "GOG"
        html = deals_landing_html(kind="promocje", games=[hit])
        assert "8.99" not in html
        assert "Quenly" in html or "quenly" in html.lower()


def test_seo_landing_prices_use_canonical_best_offers_map(db, monkeypatch) -> None:
    """Guard: collect_landing_items must call shared best_offers_map, not raw min()."""
    import app.core.seo_landings as landings

    calls: list[list[int]] = []
    real = landings.best_offers_map

    def _wrap(db_sess, game_ids, **kwargs):
        calls.append(list(game_ids))
        return real(db_sess, game_ids, **kwargs)

    monkeypatch.setattr(landings, "best_offers_map", _wrap)

    g = _game(db, title="Parity Probe", slug="parity-probe", steam_appid=900101)
    _offer(db, g, "Steam", 50.0, is_official=True)
    # Confirmed official sale vs Steam — eligible for promocje without keyshop freshness.
    _offer(
        db,
        g,
        "GOG",
        20.0,
        is_official=True,
        affiliate_url="https://www.gog.com/game/parity_probe",
    )

    landing = SeoLanding("promocje", "promocje", "Promocje", "inne", min_savings_pct=5)
    items = collect_landing_items(db, landing, build_item=_build_item, limit=60)
    assert calls, "collect_landing_items must use best_offers_map"
    assert not hasattr(landings, "_best_offers_map") or landings.best_offers_map is _wrap
    probe = next(i for i in items if i.slug == "parity-probe")
    assert probe.best_price_pln == pytest.approx(20.0)
    assert probe.best_shop_name == "GOG"
