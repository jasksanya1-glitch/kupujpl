"""Eneba PL key shop offers."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from app.core.affiliate import make_affiliate_link
from app.parsers.currency_pln import money_to_pln
from app.parsers.keyshop_common import (
    HEADERS,
    fetch_url,
    import_keyshop_offers,
    title_match_score,
)

logger = logging.getLogger("eneba_parser")

BASE = "https://www.eneba.com"
_SLUG_DELAY = float(os.environ.get("ENEBA_SLUG_DELAY_SEC", "0.8"))
GRAPHQL_URL = f"{BASE}/graphql"

_AUCTIONS_QUERY = """
query ProductPageAuctionsList(
  $first: Int!
  $slug: String!
  $currency: AvailableCurrencyType
  $isCheapestAuctionIncluded: Boolean = true
) {
  productNoCache(slug: $slug) {
    slug
    auctions(first: $first, includeCheapest: $isCheapestAuctionIncluded) {
      edges {
        node {
          slug
          isInStock
          price(currency: $currency) {
            amount
            currency
          }
        }
      }
    }
  }
}
"""


def _eneba_slug_candidates(title: str, game_slug: str) -> list[str]:
    core = game_slug
    short = "-".join([p for p in game_slug.split("-") if p][:6])
    prefixes = ("steam", "gog", "uplay", "xbox", "origin", "ea-app")
    suffixes = (
        "key-global",
        "steam-key-global",
        "pc-steam-key-global",
        "gog-com-key-global",
        "pc-gog-com-key-europe",
        "cd-key-global",
    )
    candidates: list[str] = []
    for prefix in prefixes:
        for suffix in suffixes:
            candidates.append(f"{prefix}-{core}-{suffix}")
            candidates.append(f"{prefix}-{short}-{suffix}")
    # Deduplicate while preserving order.
    return list(dict.fromkeys(c for c in candidates if len(c) > 8))


def _slug_from_kinguin_hint(title: str, game_slug: str) -> str | None:
    kinguin = fetch_url(
        f"https://www.kinguin.net/pl/catalogsearch/result/?q={quote_plus(title)}"
    )
    if kinguin is None or kinguin.status_code != 200:
        return None

    keywords = [k for k in game_slug.split("-") if len(k) > 2][:4]
    for href in re.findall(
        r'href="https://www\.kinguin\.net/[^"]+/category/\d+/([^"?]+)"',
        kinguin.text,
    ):
        hint = href.lower().replace("_", "-")
        if keywords and not all(k in hint for k in keywords):
            continue
        if any(x in hint for x in ("altergift", "account", "ps4", "ps5", "xbox")):
            continue
        drm = "steam" if "steam" in hint or "pc" in hint else "gog" if "gog" in hint else "steam"
        candidates = [
            f"{drm}-{hint}",
            f"{drm}-{hint}-key-global",
            f"{drm}-{hint}-cd-key-global",
            f"{drm}-{hint.replace('-goty-edition', '-goty')}-gog-com-key-global",
        ]
        for slug in dict.fromkeys(candidates):
            time.sleep(_SLUG_DELAY)
            page = fetch_url(f"{BASE}/pl/{slug}")
            if page is not None and page.status_code == 200:
                return slug
            if page is not None and page.status_code == 429:
                logger.warning("Eneba rate limited during slug lookup")
                return None
    return None


def _resolve_slug(title: str, game_slug: str) -> str | None:
    slug = _slug_from_kinguin_hint(title, game_slug)
    if slug:
        return slug

    for slug in _eneba_slug_candidates(title, game_slug)[:4]:
        time.sleep(_SLUG_DELAY)
        page = fetch_url(f"{BASE}/pl/{slug}")
        if page is not None and page.status_code == 200:
            if title_match_score(title, slug.replace("-", " ")) >= 0.25:
                return slug
        if page is not None and page.status_code == 429:
            break
    return None


def _graphql_price(session, slug: str) -> float | None:
    payload = {
        "operationName": "ProductPageAuctionsList",
        "query": _AUCTIONS_QUERY,
        "variables": {
            "first": 3,
            "slug": slug,
            "currency": "EUR",
            "isCheapestAuctionIncluded": True,
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Origin": BASE,
        "Referer": f"{BASE}/pl/{slug}",
        "Accept-Language": "pl-PL,pl;q=0.9",
    }
    try:
        response = session.post(GRAPHQL_URL, json=payload, headers=headers, timeout=12)
        if response.status_code != 200:
            return None
        data = response.json()
        edges = (
            data.get("data", {})
            .get("productNoCache", {})
            .get("auctions", {})
            .get("edges", [])
        )
        best: float | None = None
        for edge in edges:
            node = edge.get("node") or {}
            if node.get("isInStock") is False:
                continue
            price = node.get("price") or {}
            pln = money_to_pln(price.get("amount"), price.get("currency") or "EUR")
            if pln is not None and (best is None or pln < best):
                best = pln
        return best
    except (json.JSONDecodeError, AttributeError, TypeError) as exc:
        logger.debug("Eneba GraphQL parse error for %s: %s", slug, exc)
        return None


def search_eneba_price(query: str, game_slug: str) -> tuple[str | None, float | None]:
    from app.parsers.affiliate_feeds import affiliate_feed_lookup

    feed = affiliate_feed_lookup("Eneba", query, game_slug)
    if feed:
        return feed.url, feed.price_pln

    import requests

    slug = _resolve_slug(query, game_slug)
    if not slug:
        logger.debug("Eneba slug not found for %s", query)
        return None, None

    product_url = f"{BASE}/pl/{slug}"
    affiliate_url = make_affiliate_link(product_url, "Eneba")

    http = requests.Session()
    http.headers.update(
        {
            "User-Agent": HEADERS["User-Agent"],
            "Accept-Language": "pl-PL,pl;q=0.9",
        }
    )
    page = http.get(product_url, timeout=12)
    if page.status_code != 200:
        return None, None

    price = _graphql_price(http, slug)
    if price is None:
        logger.debug("Eneba price unavailable for %s (GraphQL blocked or no offers)", slug)
        return None, None
    return affiliate_url, price


def import_eneba_offers(db: Session, limit: int = 150) -> dict:
    return import_keyshop_offers(
        db,
        shop_name="Eneba",
        search_fn=search_eneba_price,
        limit=limit,
        delay_sec=2.0,
    )
