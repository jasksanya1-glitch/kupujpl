"""Article CMS helpers: queries, JSON import, draft creation."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, joinedload

from app.core.html_sanitize import sanitize_article_html
from app.models.models import Article, Game

logger = logging.getLogger("articles")

_BLOG_JSON = Path(__file__).resolve().parent.parent / "data" / "blog_posts.json"
DEFAULT_AUTHOR = "Redakcja KupujPL Games"
PUBLISHED = "published"
STATUSES_INDEXABLE = frozenset({PUBLISHED})


def _slugify(text: str) -> str:
    raw = (text or "").lower().strip()
    raw = re.sub(r"[^\w\s-]", "", raw, flags=re.UNICODE)
    raw = re.sub(r"[-\s]+", "-", raw).strip("-")
    return raw[:200] or "artykul"


def list_published_articles(db: Session, *, limit: int = 50) -> list[Article]:
    return (
        db.query(Article)
        .filter(Article.status == PUBLISHED)
        .order_by(Article.date_published.desc(), Article.id.desc())
        .limit(limit)
        .all()
    )


def get_article_by_slug(db: Session, slug: str, *, allow_unpublished: bool = False) -> Article | None:
    q = db.query(Article).options(joinedload(Article.game)).filter(Article.slug == slug)
    art = q.first()
    if not art:
        return None
    if not allow_unpublished and art.status != PUBLISHED:
        return None
    return art


def articles_for_game(db: Session, game_id: int, *, limit: int = 5) -> list[Article]:
    return (
        db.query(Article)
        .filter(Article.status == PUBLISHED, Article.game_id == game_id)
        .order_by(Article.date_published.desc())
        .limit(limit)
        .all()
    )


def import_legacy_blog_posts(db: Session) -> dict[str, int]:
    """One-shot import of blog_posts.json into articles (skip existing slugs)."""
    if not _BLOG_JSON.is_file():
        return {"imported": 0, "skipped": 0}
    data = json.loads(_BLOG_JSON.read_text(encoding="utf-8"))
    imported = 0
    skipped = 0
    for slug, post in data.items():
        exists = db.query(Article.id).filter(Article.slug == slug).first()
        if exists:
            skipped += 1
            continue
        date_s = (post.get("date") or "")[:10]
        try:
            pub = datetime.strptime(date_s, "%Y-%m-%d") if date_s else datetime.utcnow()
        except ValueError:
            pub = datetime.utcnow()
        desc = (post.get("description") or "").strip()
        art = Article(
            slug=slug,
            title=post.get("title") or slug,
            lead=desc,
            excerpt=desc[:600] if desc else None,
            content=sanitize_article_html(post.get("body_html") or ""),
            status=PUBLISHED,
            article_type="guide",
            author=DEFAULT_AUTHOR,
            seo_title=post.get("title"),
            seo_description=desc[:400] if desc else None,
            date_created=pub,
            date_published=pub,
            date_modified=pub,
            discover_candidate=False,
        )
        db.add(art)
        imported += 1
    if imported:
        db.commit()
        logger.info("Imported %s legacy blog posts (%s skipped)", imported, skipped)
    return {"imported": imported, "skipped": skipped}


def unique_slug(db: Session, base: str) -> str:
    slug = _slugify(base)
    if not db.query(Article.id).filter(Article.slug == slug).first():
        return slug
    for i in range(2, 50):
        cand = f"{slug}-{i}"
        if not db.query(Article.id).filter(Article.slug == cand).first():
            return cand
    return f"{slug}-{int(datetime.utcnow().timestamp())}"


def create_draft_from_candidate(
    db: Session,
    *,
    game: Game,
    reason: str,
    shop_name: str | None,
    price_current: float | None,
    price_previous: float | None,
    discount_percent: int | None,
    valid_until: datetime | None,
    title: str,
    lead: str,
    content: str,
    article_type: str,
) -> Article:
    slug = unique_slug(db, f"{game.slug}-{reason}")
    now = datetime.utcnow()
    art = Article(
        slug=slug,
        title=title[:320],
        lead=lead,
        excerpt=(lead or "")[:600],
        content=sanitize_article_html(content),
        status="draft",
        article_type=article_type,
        author=DEFAULT_AUTHOR,
        game_id=game.id,
        shop_name=shop_name,
        price_current=price_current,
        price_previous=price_previous,
        discount_percent=discount_percent,
        valid_until=valid_until,
        date_created=now,
        date_modified=now,
        date_published=None,
        discover_candidate=True,
        seo_title=title[:320],
        seo_description=(lead or "")[:400],
        featured_image=game.cover_image,
        featured_image_alt=f"Okładka gry {game.title}",
    )
    db.add(art)
    db.commit()
    db.refresh(art)
    return art


def publish_article(db: Session, article: Article) -> Article:
    now = datetime.utcnow()
    article.content = sanitize_article_html(article.content)
    article.status = PUBLISHED
    if not article.date_published:
        article.date_published = now
    article.date_modified = now
    db.commit()
    db.refresh(article)
    return article
