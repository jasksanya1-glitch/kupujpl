"""Strict HTML sanitization for editorial article bodies (bleach allowlist)."""
from __future__ import annotations

import bleach

ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "h2",
        "h3",
        "h4",
        "strong",
        "b",
        "em",
        "i",
        "ul",
        "ol",
        "li",
        "blockquote",
        "a",
        "img",
    }
)

ALLOWED_ATTRIBUTES: dict[str, list[str]] = {
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "width", "height"],
}

ALLOWED_PROTOCOLS = frozenset({"http", "https", "mailto"})


def sanitize_article_html(raw: str | None) -> str:
    """Sanitize stored/rendered article HTML. Never raises on bad input."""
    if not raw:
        return ""
    return bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
