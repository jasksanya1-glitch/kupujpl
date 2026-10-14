"""Same store must render the same classification across games."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.shops_trust import shop_trust_badge
from app.core.store_classification import StoreClass, classify_store, store_class_label_short_pl
from app.models.models import Game, Offer
from app.schemas.schemas import OfferResponse


AUTHORIZED = ("Instant Gaming", "Fanatical")


def _game(db: Session, *, title: str, slug: str) -> Game:
    g = Game(
        title=title,
        slug=slug,
        steam_appid=abs(hash(slug)) % 9_000_000,
        platform="pc",
        steam_review_count=1000,
        steam_enriched=True,
    )
    db.add(g)
    db.flush()
    return g


def _offer(db: Session, game: Game, shop: str, price: float) -> Offer:
    o = Offer(
        game_id=game.id,
        shop_name=shop,
        price_pln=price,
        affiliate_url=f"https://example.test/{shop}/{game.slug}",
        is_official=shop in {"Steam", "GOG", "Epic Games"},
        in_stock=True,
        match_confidence=1.2,
    )
    db.add(o)
    db.flush()
    return o


def test_authorized_resellers_classify_consistently():
    for shop in AUTHORIZED:
        assert classify_store(shop) is StoreClass.AUTHORIZED_RESELLER
        badge = shop_trust_badge(shop, is_official=False)
        assert badge["store_class"] == "AUTHORIZED_RESELLER"
        assert badge["label"] == store_class_label_short_pl(StoreClass.AUTHORIZED_RESELLER)
        assert "Marketplace" not in badge["label"]


def test_same_store_same_label_across_games(db: Session):
    g1 = _game(db, title="Game One", slug="game-one-cls")
    g2 = _game(db, title="Game Two", slug="game-two-cls")
    for shop in AUTHORIZED:
        _offer(db, g1, shop, 10.0)
        _offer(db, g2, shop, 20.0)
    db.commit()

    labels = {}
    for g in (g1, g2):
        for o in db.query(Offer).filter(Offer.game_id == g.id).all():
            if o.shop_name not in AUTHORIZED:
                continue
            badge = shop_trust_badge(o.shop_name, is_official=o.is_official)
            labels.setdefault(o.shop_name, set()).add(
                (badge["store_class"], badge["label"])
            )
    for shop in AUTHORIZED:
        assert len(labels[shop]) == 1
        sc, label = next(iter(labels[shop]))
        assert sc == "AUTHORIZED_RESELLER"
        assert label == "Autoryzowany"


def test_offer_response_exposes_store_class():
    # Schema-level: OfferResponse accepts store_class from badge.
    resp = OfferResponse(
        id=1,
        game_id=1,
        shop_name="Instant Gaming",
        price_pln=48.03,
        affiliate_url="https://example.test/ig",
        is_official=False,
        in_stock=True,
        updated_at=__import__("datetime").datetime.utcnow(),
        trust_label="Autoryzowany",
        store_class="AUTHORIZED_RESELLER",
    )
    assert resp.store_class == "AUTHORIZED_RESELLER"
    assert resp.trust_label == "Autoryzowany"
