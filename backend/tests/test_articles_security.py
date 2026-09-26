"""Security tests for Discover/News: XSS, JSON-LD breakout, CSRF, absolute URLs."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from app.core.html_sanitize import sanitize_article_html
from app.core.json_ld_safe import absolute_public_asset_url, ensure_valid_json_ld
from app.core.panel3_auth import (
    panel3_csrf_token,
    require_panel3_admin,
    require_panel3_csrf,
)
from app.core.seo_pages import blog_landing_html, blog_rss_xml, sitemap_blog_xml, sitemap_news_xml
from app.models.models import Article, Base


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


def _request(*, headers: dict[str, str] | None = None, cookies: dict[str, str] | None = None) -> Request:
    hdrs = []
    for k, v in (headers or {}).items():
        hdrs.append((k.lower().encode(), v.encode()))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "headers": hdrs,
        "path": "/api/admin/articles/1/publish",
        "raw_path": b"/api/admin/articles/1/publish",
        "root_path": "",
        "scheme": "https",
        "query_string": b"",
        "client": ("127.0.0.1", 123),
        "server": ("test", 443),
    }
    req = Request(scope)
    if cookies:
        # Starlette reads cookies from cookie header
        cookie = "; ".join(f"{k}={v}" for k, v in cookies.items())
        scope["headers"] = list(scope["headers"]) + [(b"cookie", cookie.encode())]
        req = Request(scope)
    return req


# ---------- XSS ----------


def test_sanitize_strips_script_and_handlers():
    raw = """
    <h2>Hello</h2>
    <script>alert(1)</script>
    <img src="/x.jpg" onerror="alert(2)">
    <a href="javascript:alert(3)">bad</a>
    <a href="https://example.com">good</a>
    <iframe src="https://evil"></iframe>
    <svg onload="alert(4)"></svg>
    <p onclick="alert(5)">click</p>
    """
    out = sanitize_article_html(raw)
    low = out.lower()
    assert "<script" not in low
    assert "onerror" not in low
    assert "onclick" not in low
    assert "javascript:" not in low
    assert "<iframe" not in low
    assert "<svg" not in low
    assert "<h2>Hello</h2>" in out
    assert 'href="https://example.com"' in out
    assert "<img" in out
    assert 'src="/x.jpg"' in out


def test_article_render_sanitizes_stored_xss(db: Session):
    art = Article(
        slug="xss-draft",
        title="XSS check",
        content='<h2>Hi</h2><script>alert(1)</script><img src="/x.jpg" onerror="alert(2)">',
        status="published",
        article_type="guide",
        date_published=datetime.utcnow(),
        date_modified=datetime.utcnow(),
    )
    db.add(art)
    db.commit()
    html = blog_landing_html("xss-draft", db)
    assert html is not None
    low = html.lower()
    assert "<script>alert" not in low
    assert "onerror=" not in low
    assert "<h2>Hi</h2>" in html


# ---------- JSON-LD ----------


def test_json_ld_breakout_escaped():
    payload = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": "</script><script>alert(1)</script>",
        "description": "ok & more",
    }
    embedded = ensure_valid_json_ld(payload)
    assert "</script>" not in embedded
    assert "<script>" not in embedded
    assert "\\u003c" in embedded
    parsed = json.loads(embedded)
    assert parsed["headline"].startswith("</script>")
    html = f'<script type="application/ld+json">{embedded}</script>'
    assert html.count("<script") == 1


def test_article_json_ld_no_breakout_in_page(db: Session):
    art = Article(
        slug="ld-break",
        title="</script><script>alert(1)</script>",
        content="<p>body</p>",
        lead="desc </script>",
        status="published",
        article_type="news",
        date_published=datetime.utcnow(),
        date_modified=datetime.utcnow(),
    )
    db.add(art)
    db.commit()
    html = blog_landing_html("ld-break", db)
    assert html is not None
    assert html.count("<script") == html.count("</script>")
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert m
    data = json.loads(m.group(1))
    assert "alert(1)" in data["headline"]


# ---------- Absolute URLs ----------


def test_absolute_public_asset_url():
    abs_u = absolute_public_asset_url("/static/x.jpg")
    assert abs_u.startswith("https://")
    already = absolute_public_asset_url("https://kupujpl.pl/games/og/logo.png")
    assert already == "https://kupujpl.pl/games/og/logo.png"


def test_og_image_absolute_on_article(db: Session):
    art = Article(
        slug="og-abs",
        title="OG",
        content="<p>x</p>",
        status="published",
        article_type="guide",
        featured_image="/static/cover.jpg",
        date_published=datetime.utcnow(),
        date_modified=datetime.utcnow(),
    )
    db.add(art)
    db.commit()
    html = blog_landing_html("og-abs", db)
    assert 'property="og:image" content="https://' in html
    assert 'content="/static/' not in html


# ---------- CSRF ----------


def test_admin_unauth_401():
    req = _request()
    with pytest.raises(HTTPException) as ei:
        require_panel3_admin(req)
    assert ei.value.status_code == 401


def test_admin_auth_missing_csrf_403():
    req = _request(headers={"X-Panel3-Code": "1408"})
    require_panel3_admin(req)
    with pytest.raises(HTTPException) as ei:
        require_panel3_csrf(req)
    assert ei.value.status_code == 403


def test_admin_auth_invalid_csrf_403():
    req = _request(headers={"X-Panel3-Code": "1408", "X-CSRF-Token": "deadbeef" * 8})
    require_panel3_admin(req)
    with pytest.raises(HTTPException) as ei:
        require_panel3_csrf(req)
    assert ei.value.status_code == 403


def test_admin_auth_valid_csrf_ok():
    token = panel3_csrf_token()
    req = _request(headers={"X-Panel3-Code": "1408", "X-CSRF-Token": token})
    require_panel3_admin(req)
    require_panel3_csrf(req)  # does not raise


# ---------- Regression ----------


def test_legacy_style_articles_and_feeds(db: Session):
    arts = []
    for i, slug in enumerate(
        [
            "jak-kupowac-gry-taniej",
            "steam-vs-keyshopy",
            "gdzie-kupic-klucz-steam",
            "alert-cenowy-jak-dziala",
            "najwieksze-oszczednosci-steam",
        ]
    ):
        arts.append(
            Article(
                slug=slug,
                title=f"Title {i}",
                content=f"<p>Paragraph {i}</p><h2>Sec</h2><ul><li>a</li></ul>",
                status="published",
                article_type="guide",
                date_published=datetime.utcnow() - timedelta(days=i + 1),
                date_modified=datetime.utcnow() - timedelta(days=i + 1),
            )
        )
    db.add_all(arts)
    db.commit()
    for a in arts:
        html = blog_landing_html(a.slug, db)
        assert html and "<p>Paragraph" in html
        assert "max-image-preview:large" in html
    assert "jak-kupowac-gry-taniej" in sitemap_blog_xml(db)
    rss = blog_rss_xml(db)
    assert "<?xml" in rss and "jak-kupowac-gry-taniej" in rss
    news = sitemap_news_xml(db)
    assert "<?xml" in news
