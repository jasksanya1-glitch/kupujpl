"""Sitemap membership must match SSR best-offer indexable for the same DB state."""
from __future__ import annotations

import re
from xml.sax.saxutils import unescape

import time

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core import seo_pages as seo_pages_mod

from app.core.catalog_cache import bump_catalog_generation
from app.core.game_offer_selection import best_offers_map
from app.core.game_page_html import game_interactive_html
from app.core.offer_quality import offer_is_suspicious_outlier
from app.core.seo_pages import (
    SITEMAP_MAX_UNCOMPRESSED_BYTES,
    SITEMAP_URL_LIMIT,
    SitemapEntryTooLargeError,
    _game_page_url,
    _urlset_xml,
    clear_game_sitemap_cache,
    iter_indexable_game_sitemap_urls,
    pack_sitemap_url_shards,
    sitemap_games_shard_xml,
    sitemap_games_xml,
    sitemap_index_xml,
)
from app.core.site_config import SITE_ORIGIN
from app.models.models import Base, Game, Offer

LOC_RE = re.compile(r"<loc>(.*?)</loc>")


def filter_display_offers(offers, *, steam_price_pln, peer_prices):
    """Mirrors app.main._filter_display_offers without importing the FastAPI app."""
    kept = [
        o
        for o in offers
        if o.is_official
        or not offer_is_suspicious_outlier(
            o, steam_price_pln=steam_price_pln, peer_prices=peer_prices
        )
    ]
    return kept or list(offers)


@pytest.fixture
def db() -> Session:
    bump_catalog_generation()
    clear_game_sitemap_cache()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        clear_game_sitemap_cache()


def add_game(db: Session, slug: str, *, platform: str = "pc", title: str | None = None) -> Game:
    game = Game(title=title or slug, slug=slug, platform=platform)
    db.add(game)
    db.flush()
    return game


def add_offer(
    db: Session,
    game: Game,
    *,
    shop_name: str,
    price_pln: float,
    in_stock: bool = True,
    is_official: bool = False,
    match_confidence: float | None = None,
    activation_region: str = "eu",
    affiliate_url: str = "https://example.test/o",
) -> Offer:
    offer = Offer(
        game_id=game.id,
        shop_name=shop_name,
        price_pln=price_pln,
        in_stock=in_stock,
        is_official=is_official,
        match_confidence=match_confidence,
        activation_region=activation_region,
        affiliate_url=affiliate_url,
    )
    db.add(offer)
    db.flush()
    return offer


def parse_locs(xml: str) -> list[str]:
    return [unescape(item) for item in LOC_RE.findall(xml)]


def game_locs(xml: str) -> list[str]:
    prefix = f"{SITE_ORIGIN}/gra/"
    return [loc for loc in parse_locs(xml) if loc.startswith(prefix)]


def all_game_sitemap_locs(db: Session) -> list[str]:
    xml = sitemap_index_xml(db)
    out: list[str] = []
    for loc in parse_locs(xml):
        if "/sitemap-games-" not in loc:
            continue
        shard = int(loc.rsplit("-", 1)[-1].removesuffix(".xml"))
        shard_xml = sitemap_games_shard_xml(db, shard)
        assert shard_xml is not None
        out.extend(game_locs(shard_xml))
    return out


def ssr_indexable_urls(db: Session) -> set[str]:
    games = db.query(Game).filter(Game.slug.isnot(None), Game.slug != "").order_by(Game.id).all()
    best = best_offers_map(db, [g.id for g in games], region="pl")
    return {_game_page_url(g.slug) for g in games if g.id in best}


def test_noindex_html_when_not_indexable():
    html = game_interactive_html(
        title="Thin Game",
        slug="thin-game",
        description=None,
        cover_image=None,
        best_price_pln=None,
        best_shop_name=None,
        indexable=False,
    )
    assert 'content="noindex, follow"' in html
    indexed = game_interactive_html(
        title="Priced Game",
        slug="priced-game",
        description=None,
        cover_image=None,
        best_price_pln=19.99,
        best_shop_name="Steam",
        indexable=True,
    )
    assert 'content="index, follow"' in indexed


def test_noindex_games_are_absent_from_sitemap(db: Session):
    indexed = add_game(db, "has-best")
    add_offer(db, indexed, shop_name="Steam", price_pln=49.99, is_official=True)
    missing = add_game(db, "no-best")
    add_offer(
        db,
        missing,
        shop_name="Instant Gaming",
        price_pln=12.0,
        match_confidence=0.1,
        is_official=False,
    )
    db.flush()
    urls = set(all_game_sitemap_locs(db))
    assert _game_page_url("has-best") in urls
    assert _game_page_url("no-best") not in urls
    assert urls == ssr_indexable_urls(db)


def test_offer_filters_match_ssr_and_sitemap(db: Session):
    cases = [
        ("na-only", dict(shop_name="Instant Gaming", price_pln=20, match_confidence=0.9, activation_region="na")),
        ("unknown-shop", dict(shop_name="Grey Market", price_pln=15, match_confidence=0.9)),
        ("steam-us", dict(shop_name="Steam US", price_pln=40, is_official=True, activation_region="na")),
        ("out-of-stock", dict(shop_name="Steam", price_pln=30, is_official=True, in_stock=False)),
        ("zero-price", dict(shop_name="Steam", price_pln=0, is_official=True)),
        ("low-confidence", dict(shop_name="Instant Gaming", price_pln=25, match_confidence=0.2)),
    ]
    for slug, kwargs in cases:
        add_offer(db, add_game(db, slug), **kwargs)

    trusted = add_game(db, "trusted-steam")
    add_offer(db, trusted, shop_name="Steam", price_pln=59.99, is_official=True)

    peer = add_game(db, "peer-outlier")
    add_offer(db, peer, shop_name="Steam", price_pln=200, is_official=True)
    add_offer(db, peer, shop_name="Instant Gaming", price_pln=15, match_confidence=0.95)

    db.flush()
    sitemap = set(all_game_sitemap_locs(db))
    ssr = ssr_indexable_urls(db)
    assert sitemap == ssr
    assert _game_page_url("trusted-steam") in sitemap
    assert _game_page_url("peer-outlier") in sitemap
    best_peer = best_offers_map(db, [peer.id], region="pl")[peer.id]
    assert best_peer.shop_name == "Steam"
    for slug, _kwargs in cases:
        assert _game_page_url(slug) not in sitemap


def test_display_fallback_does_not_make_sitemap_indexable(db: Session):
    game = add_game(db, "display-only")
    offer = add_offer(
        db,
        game,
        shop_name="Instant Gaming",
        price_pln=9.0,
        match_confidence=0.1,
        is_official=False,
    )
    db.flush()
    displayed = filter_display_offers([offer], steam_price_pln=80.0, peer_prices=[9.0])
    assert displayed == [offer]
    assert game.id not in best_offers_map(db, [game.id], region="pl")
    assert _game_page_url("display-only") not in set(all_game_sitemap_locs(db))


def test_canonical_urls_only_no_spa_duplicates(db: Session):
    game = add_game(db, "canonical-slug")
    add_offer(db, game, shop_name="Steam", price_pln=10, is_official=True)
    db.flush()
    xml = sitemap_games_xml(db, limit=1)
    assert f"{SITE_ORIGIN}/?gra=canonical-slug" not in xml
    locs = parse_locs(xml)
    assert locs.count(_game_page_url("canonical-slug")) == 1
    assert locs[0] == f"{SITE_ORIGIN}/"


def test_no_duplicate_urls_across_shards():
    homepage = (f"{SITE_ORIGIN}/", "2026-01-01", "daily", "1.0")
    games = [
        (f"{SITE_ORIGIN}/gra/g{i}", "2026-01-01", "weekly", "0.7") for i in range(100_001)
    ]
    shards = pack_sitemap_url_shards([homepage, *games])
    expected = [homepage[0], *[item[0] for item in games]]
    flat = [entry[0] for shard in shards for entry in shard]
    assert flat == expected
    assert len(flat) == 100_002
    assert len(set(flat)) == 100_002
    assert all(len(shard) <= SITEMAP_URL_LIMIT for shard in shards)
    assert len(shards) == 3


@pytest.mark.parametrize("game_count, expected_shards", [(49_999, 1), (50_000, 2), (50_001, 2)])
def test_url_limit_boundaries_include_homepage(game_count: int, expected_shards: int):
    homepage = (f"{SITE_ORIGIN}/", "2026-01-01", "daily", "1.0")
    games = [
        (f"{SITE_ORIGIN}/gra/g{i}", "2026-01-01", "weekly", "0.7") for i in range(game_count)
    ]
    shards = pack_sitemap_url_shards([homepage, *games])
    expected = [homepage[0], *[item[0] for item in games]]
    flat = [entry[0] for shard in shards for entry in shard]
    assert flat == expected
    assert len(shards) == expected_shards
    assert sum(len(shard) for shard in shards) == game_count + 1
    assert all(len(shard) <= SITEMAP_URL_LIMIT for shard in shards)
    if expected_shards > 1:
        assert len(shards[0]) == SITEMAP_URL_LIMIT


def test_byte_limit_splits_before_fifty_mb():
    huge = ("https://kupujpl.pl/games/gra/" + ("a" * 2_000_000), "2026-01-01", "weekly", "0.7")
    shards = pack_sitemap_url_shards([huge] * 30)
    assert len(shards) > 1
    for shard in shards:
        raw = _urlset_xml(shard).encode("utf-8")
        raw = _urlset_xml(shard).encode("utf-8")
        assert len(raw) <= SITEMAP_MAX_UNCOMPRESSED_BYTES
        assert len(shard) <= SITEMAP_URL_LIMIT


def test_oversized_entry_is_rejected():
    huge = ("https://kupujpl.pl/games/gra/" + ("a" * 400), "2026-01-01", "weekly", "0.7")
    ok = (f"{SITE_ORIGIN}/gra/fits", "2026-01-01", "weekly", "0.7")
    with pytest.raises(SitemapEntryTooLargeError, match="does not fit in one uncompressed sitemap"):
        pack_sitemap_url_shards([huge, ok], max_bytes=400)
    shards = pack_sitemap_url_shards([ok], max_bytes=400)
    assert [entry[0] for shard in shards for entry in shard] == [ok[0]]
    assert len(_urlset_xml(shards[0]).encode("utf-8")) <= 400


def test_old_sitemap_games_url_is_first_shard(db: Session):
    game = add_game(db, "first-shard")
    add_offer(db, game, shop_name="Steam", price_pln=11, is_official=True)
    db.flush()
    assert sitemap_games_xml(db) == sitemap_games_shard_xml(db, 1)
    index = sitemap_index_xml(db)
    assert f"{SITE_ORIGIN}/sitemap-games-1.xml" in index
    assert sitemap_games_shard_xml(db, 0) is None
    assert sitemap_games_shard_xml(db, 2) is None


def test_cache_invalidates_when_offer_eligibility_changes(db: Session):
    game = add_game(db, "cache-game")
    offer = add_offer(db, game, shop_name="Steam", price_pln=22, is_official=True)
    db.flush()
    assert _game_page_url("cache-game") in set(all_game_sitemap_locs(db))
    offer.in_stock = False
    db.flush()
    # Same generation still serves the previous snapshot.
    assert _game_page_url("cache-game") in set(all_game_sitemap_locs(db))
    bump_catalog_generation()
    sitemap = set(all_game_sitemap_locs(db))
    ssr = ssr_indexable_urls(db)
    assert sitemap == ssr
    assert _game_page_url("cache-game") not in sitemap


def test_cache_expires_without_generation_bump(db: Session, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(seo_pages_mod, "SITEMAP_CACHE_TTL_SEC", 0.05)
    game = add_game(db, "ttl-game")
    offer = add_offer(db, game, shop_name="Steam", price_pln=18, is_official=True)
    db.flush()
    assert _game_page_url("ttl-game") in set(all_game_sitemap_locs(db))
    offer.in_stock = False
    db.flush()
    assert _game_page_url("ttl-game") in set(all_game_sitemap_locs(db))
    time.sleep(0.06)
    sitemap = set(all_game_sitemap_locs(db))
    assert sitemap == ssr_indexable_urls(db)
    assert _game_page_url("ttl-game") not in sitemap


def test_sitemap_generation_is_batched_and_read_only(db: Session):
    statements: list[str] = []

    @event.listens_for(db.bind, "before_cursor_execute")
    def _count(_conn, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    for i in range(120):
        game = add_game(db, f"batch-{i:03d}")
        add_offer(db, game, shop_name="Steam", price_pln=10 + (i % 5), is_official=True)
    db.flush()
    statements.clear()
    batched = iter_indexable_game_sitemap_urls(db, batch_size=40)
    assert len(batched) == 120
    dml = [
        sql
        for sql in statements
        if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
    ]
    assert dml == []
    selects = [sql for sql in statements if sql.lstrip().upper().startswith("SELECT")]
    # 120 games / batch 40 → 3 batches × (games + steam + offers + lastmod).
    assert 8 <= len(selects) <= 20
    statements.clear()
    urls = all_game_sitemap_locs(db)
    assert len(urls) == 120
    assert len(urls) == len(set(urls))
    dml = [
        sql
        for sql in statements
        if sql.lstrip().split(" ", 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
    ]
    assert dml == []
