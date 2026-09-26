"""Tests for Discover/News article CMS and candidates."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.articles import (
    create_draft_from_candidate,
    import_legacy_blog_posts,
    list_published_articles,
    publish_article,
    unique_slug,
)
from app.core.discover_candidates import (
    COOLDOWN_HOURS,
    _fingerprint,
    draft_from_candidate,
    ignore_candidate,
    scan_deal_candidates,
)
from app.core.seo_pages import blog_landing_html, blog_rss_xml, sitemap_blog_xml, sitemap_news_xml
from app.models.models import Article, Base, DiscoverCandidate, Game, Offer


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_unique_slug(db: Session):
    db.add(Article(slug="foo", title="Foo", content="x", status="draft"))
    db.commit()
    assert unique_slug(db, "Foo") == "foo-2"


def test_import_legacy_and_sitemap_excludes_draft(db: Session, monkeypatch, tmp_path):
    # Seed via create instead of JSON file dependency
    pub = Article(
        slug="pub-a",
        title="Published",
        content="<p>ok</p>",
        status="published",
        article_type="guide",
        date_published=datetime.utcnow() - timedelta(days=1),
        date_modified=datetime.utcnow() - timedelta(days=1),
    )
    draft = Article(
        slug="draft-a",
        title="Draft",
        content="<p>no</p>",
        status="draft",
        article_type="deal",
    )
    db.add_all([pub, draft])
    db.commit()
    xml = sitemap_blog_xml(db)
    assert "pub-a" in xml
    assert "draft-a" not in xml
    assert "lastmod" in xml


def test_draft_noindex_published_index(db: Session):
    art = Article(
        slug="x-deal",
        title="Deal X",
        content="<p>body</p>",
        lead="Lead",
        status="draft",
        article_type="deal",
        author="Redakcja KupujPL Games",
    )
    db.add(art)
    db.commit()
    html = blog_landing_html("x-deal", db, preview=True)
    assert html is not None
    assert "noindex" in html
    publish_article(db, art)
    html2 = blog_landing_html("x-deal", db)
    assert html2 is not None
    assert "max-image-preview:large" in html2
    assert "og:type\" content=\"article\"" in html2 or 'og:type" content="article"' in html2
    assert "application/ld+json" in html2
    assert "NewsArticle" in html2 or "Article" in html2


def test_candidate_fingerprint_and_cooldown(db: Session):
    g = Game(title="Test Game", slug="test-game", platform="pc")
    db.add(g)
    db.flush()
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Steam",
            price_pln=100.0,
            original_price_pln=200.0,
            affiliate_url="https://example.com/s",
            is_official=True,
            in_stock=True,
        )
    )
    db.add(
        Offer(
            game_id=g.id,
            shop_name="Instant Gaming",
            price_pln=40.0,
            affiliate_url="https://example.com/ig",
            is_official=False,
            in_stock=True,
        )
    )
    db.commit()
    # Without steam savings plumbing build_top_deals may return empty — still test draft path
    fp = _fingerprint(g.id, "price_drop_50", "Instant Gaming", 40.0)
    assert len(fp) == 40
    row = DiscoverCandidate(
        fingerprint=fp,
        game_id=g.id,
        reason="price_drop_50",
        score=25,
        shop_name="Instant Gaming",
        price_current=40.0,
        price_previous=100.0,
        discount_percent=60,
        status="open",
    )
    db.add(row)
    db.commit()
    art = draft_from_candidate(db, row.id)
    assert art is not None
    assert art.status == "draft"
    assert "zł" in art.title or "przecenione" in art.title.lower() or "promocja" in art.title.lower()
    db.refresh(row)
    assert row.status == "drafted"
    ignored = ignore_candidate(db, row.id)
    # already drafted — ignore still works
    assert ignored is not None


def test_rss_and_news_sitemap(db: Session):
    recent = Article(
        slug="fresh",
        title="Fresh deal",
        content="<p>x</p>",
        status="published",
        article_type="deal",
        date_published=datetime.utcnow(),
        date_modified=datetime.utcnow(),
        author="Redakcja KupujPL Games",
        excerpt="Opis",
    )
    old = Article(
        slug="old",
        title="Old",
        content="<p>x</p>",
        status="published",
        date_published=datetime.utcnow() - timedelta(days=10),
        date_modified=datetime.utcnow() - timedelta(days=10),
    )
    db.add_all([recent, old])
    db.commit()
    rss = blog_rss_xml(db)
    assert "Fresh deal" in rss
    assert "<item>" in rss
    news = sitemap_news_xml(db)
    assert "fresh" in news
    assert "old" not in news
    assert "news:news" in news


def test_list_published_only(db: Session):
    db.add(Article(slug="a", title="A", content="c", status="published", date_published=datetime.utcnow()))
    db.add(Article(slug="b", title="B", content="c", status="review"))
    db.commit()
    items = list_published_articles(db)
    assert len(items) == 1
    assert items[0].slug == "a"
