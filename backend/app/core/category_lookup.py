"""Resolve category slugs (aliases + Polish Steam genre names)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.models import Category

from app.core.curated_categories import is_curated_slug

# Frontend / home section slug → DB slug (Steam PL genre names after slugify)
CATEGORY_SLUG_ALIASES: dict[str, str] = {
    "strategie": "strategiczne",
    "rekreacyjne": "casual",
    "indie": "niezalezne",
    "horror": "horror",
    "akcja": "akcja",
    "rpg": "rpg",
    "przygodowe": "przygodowe",
    "symulacje": "symulacje",
    "sportowe": "sportowe",
    "niezalezne": "niezalezne",
}


def resolve_category_slug(db: Session, slug: str | None) -> str | None:
    if not slug:
        return None
    slug = slug.strip().lower()
    if not slug:
        return None

    if is_curated_slug(slug):
        return slug

    direct = db.query(Category).filter(Category.slug == slug).first()
    if direct:
        return direct.slug

    alias = CATEGORY_SLUG_ALIASES.get(slug)
    if alias:
        aliased = db.query(Category).filter(Category.slug == alias).first()
        if aliased:
            return aliased.slug

    by_name = (
        db.query(Category)
        .filter(Category.name.ilike(slug.replace("-", " ")))
        .first()
    )
    if by_name:
        return by_name.slug

    return slug
