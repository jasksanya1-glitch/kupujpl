"""Public visibility rules for catalog categories."""
from __future__ import annotations

HIDDEN_PUBLIC_CATEGORY_SLUGS = frozenset({"free-to-play"})


def is_hidden_public_category_slug(slug: str | None) -> bool:
    if not slug:
        return False
    return slug.strip().lower() in HIDDEN_PUBLIC_CATEGORY_SLUGS
