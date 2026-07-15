"""Partner product feeds (Awin CSV, G2A XML) — lookup prices without HTML scraping."""
from __future__ import annotations

import csv
import gzip
import io
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import requests
from dotenv import load_dotenv

from app.core.affiliate import make_affiliate_link
from app.core.database import BASE_DIR
from app.parsers.currency_pln import money_to_pln, to_pln
from app.parsers.keyshop_common import (
    MIN_MATCH_SCORE,
    classify_keyshop_product,
    is_restricted_region_listing,
    slugify,
    title_match_score,
)

load_dotenv(BASE_DIR / ".env")

logger = logging.getLogger("affiliate_feeds")

_CACHE_DIR = Path(BASE_DIR) / "tmp" / "affiliate_feeds"
_CACHE_TTL_SEC = int(os.environ.get("AFFILIATE_FEED_CACHE_HOURS", "6")) * 3600

_AWIN_LIST_BASE = "https://productdata.awin.com/datafeed/list/apikey"
_AWIN_DOWNLOAD_BASE = "https://productdata.awin.com/datafeed/download/apikey"
_AWIN_LEGACY_DOWNLOAD_BASE = "https://legacydatafeeds.awin.com/datafeed/download/apikey"
_CATALOG_TTL_SEC = 3600
_DEFAULT_GAMIVO_FEED_URLS = (
    "https://www.gamivo.com/feed/pln/en/feed-cs-new.xml",
    "https://www.gamivo.com/feed/eur/en/feed-cs-new.xml",
    "https://www.gamivo.com/feed/usd/en/feed-cs-new.xml",
    "https://www.gamivo.com/feed/gbp/en/feed-cs-new.xml",
    "https://www.gamivo.com/feed/cad/en/feed-cs-new.xml",
)


def _awin_api_key() -> str:
    return os.environ.get("AWIN_DATAFEED_API_KEY", "").strip()


# Awin advertiser (merchant) IDs — override in env after joining each program.
_DEFAULT_MERCHANT_IDS: dict[str, str] = {
    "G2A": "11280",
    "Kinguin": "32217",
    "CDKeys": "",
    "Gamivo": "",
    "Eneba": "19520",  # Eneba ES on Awin; override via AWIN_FEED_MERCHANT_ENEBA
    "Fanatical": "118821",  # Fanatical Global on Awin
}

_CSV_COLUMNS = (
    "aw_deep_link,product_name,search_price,store_price,merchant_product_id,"
    "in_stock,merchant_category,brand_name,currency,description"
)

_catalog_cache: tuple[float, list["FeedCatalogEntry"], str | None] | None = None


@dataclass(frozen=True)
class FeedCatalogEntry:
    advertiser_id: str
    advertiser_name: str
    join_status: str
    feed_id: str
    download_url: str | None


@dataclass(frozen=True)
class FeedMatch:
    url: str
    price_pln: float
    confidence: float
    source: str = "awin_feed"
    product_title: str | None = None


@dataclass
class _FeedRow:
    name: str
    url: str
    price_raw: float
    currency: str
    in_stock: bool


_last_download_errors: dict[str, str] = {}
_SHOP_ROWS_CACHE: dict[str, tuple[float, list["_FeedRow"], dict[str, list[int]]]] = {}
_OPAQUE_AWIN_MIN_SCORE = float(os.environ.get("OPAQUE_AWIN_FEED_MIN_SCORE", "0.75"))

_G2A_FEED_SKIP = (
    "account",
    "random",
    "try-to-get",
    "xbox",
    "psn",
    "playstation",
    "nintendo",
    "switch",
    "subscription",
    "gift card",
    "gift-card",
    "steam gift",
    "steam-gift",
    " gift ",
    "-gift-",
    "wallet",
    " points",
    " xp ",
    "-xp-",
    "double xp",
    "double-xp",
    "boost",
    "software",
    "cd-key-random",
)

_G2A_FEED_PREFER = (
    "steam-key-global",
    "pc-steam",
    "steam-cd-key",
    "gog",
    "epic-games",
)

_INDEX_STOP = frozenset(
    {"the", "a", "an", "of", "and", "for", "pc", "game", "edition", "global", "pl", "key"}
)

# Polish Steam title tokens -> common English feed tokens (G2A XML is mostly EN).
_G2A_PL_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "wiedzmin": ("witcher",),
    "dziki": ("wild",),
    "gon": ("hunt",),
    "swiat": ("world",),
    "wojny": ("war",),
    "cieni": ("shadow",),
    "mrocznych": ("dark",),
    "soul": ("souls",),
    "smierci": ("death",),
    "zelda": ("zelda",),
    "potter": ("potter",),
    # Destiny 2 DLC (PL Steam titles vs EN G2A feed)
    "upadek": ("lightfall",),
    "swiatla": ("lightfall",),
    "zanurzenie": ("deep", "depths"),
    "glebiny": ("deep", "depths"),
    "wichrowa": ("witch", "queen"),
    "krolowa": ("queen",),
    "wygasajace": ("beyond", "light"),
    "swiatlo": ("light",),
}


def _g2a_alias_tokens(token: str) -> set[str]:
    aliases = _G2A_PL_TOKEN_ALIASES.get(token)
    return set(aliases) if aliases else set()


def _is_opaque_awin_url(url: str) -> bool:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    path = (parsed.path or "").lower()
    return ("awin1.com" in host or "awstrack.me" in host) and path.endswith("/pclick.php")


def _url_with_feed_title(url: str, product_title: str) -> str:
    """Keep feed URLs attributable while preserving the feed title for validation."""
    if not product_title:
        return url
    parsed = urlparse(url)
    if not (_is_opaque_awin_url(url) or "gamivo.com" in parsed.netloc.lower()):
        return url
    fragment_params = dict(parse_qsl(parsed.fragment))
    fragment_params.setdefault("kp_title", product_title)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            parsed.query,
            urlencode(fragment_params),
        )
    )


def _merchant_id(shop: str) -> str | None:
    env_key = f"AWIN_FEED_MERCHANT_{shop.upper().replace(' ', '_')}"
    mid = os.environ.get(env_key, "").strip()
    if mid:
        return mid
    return (_DEFAULT_MERCHANT_IDS.get(shop) or "").strip() or None


def _custom_feed_url(shop: str) -> str | None:
    urls = _custom_feed_urls(shop)
    return urls[0] if urls else None


def _custom_feed_urls(shop: str) -> list[str]:
    shop_key = shop.upper().replace(" ", "_")
    raw_values = [
        os.environ.get(f"AFFILIATE_FEED_URLS_{shop_key}", ""),
        os.environ.get(f"AFFILIATE_FEED_URL_{shop_key}", ""),
    ]
    urls: list[str] = []
    for raw in raw_values:
        for url in re.split(r"[\s,]+", raw.strip()):
            if url and url.startswith(("http://", "https://")) and url not in urls:
                urls.append(url)
    if not urls and shop == "Gamivo":
        urls.extend(_DEFAULT_GAMIVO_FEED_URLS)
    return urls


def _cache_path(shop: str) -> Path:
    safe = re.sub(r"[^\w]+", "_", shop.lower())
    return _CACHE_DIR / f"{safe}.csv"


def _index_tokens(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        for token in slugify(part).split("-"):
            if token and token not in _INDEX_STOP and len(token) > 2:
                tokens.add(token)
    return tokens


def _g2a_significant_tokens(*parts: str) -> set[str]:
    """G2A tokens — keep short years/editions (25, v) dropped by _index_tokens."""
    tokens: set[str] = set()
    for part in parts:
        for token in slugify(part).split("-"):
            if not token or token in _INDEX_STOP:
                continue
            if len(token) > 2:
                tokens.add(token)
            elif token.isdigit() and len(token) >= 2:
                tokens.add(token)
            elif len(token) == 1 and token.isalpha():
                tokens.add(token)
    return tokens


def _is_short_g2a_title(query: str, game_slug: str) -> bool:
    sig = _g2a_significant_tokens(query, _normalize_game_slug(game_slug).replace("-", " "))
    if not sig:
        return False
    if len(sig) <= 2 and len((query or "").strip()) < 28:
        return True
    if len(sig) <= 3 and any(t.isdigit() for t in sig):
        return True
    return False


def _g2a_lookup_variants(query: str, game_slug: str) -> list[tuple[str, str]]:
    """Alternate title/slug pairs for feed lookup (short PL names, slug from Steam appid)."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []

    def _add(q: str, slug: str) -> None:
        q = (q or "").strip()
        slug = (slug or "").strip()
        if not q:
            return
        key = (q.casefold(), slug.casefold())
        if key in seen:
            return
        seen.add(key)
        out.append((q, slug or slugify(q)))

    _add(query, game_slug)
    slug_base = _normalize_game_slug(game_slug)
    slug_title = slug_base.replace("-", " ").strip()
    if slug_title and slug_title.casefold() != (query or "").casefold():
        _add(slug_title, game_slug)
    return out

def _normalize_game_slug(game_slug: str) -> str:
    """Strip trailing Steam appid suffix (e.g. hogwarts-legacy-990080 -> hogwarts-legacy)."""
    return re.sub(r"-\d+$", "", (game_slug or "").strip())


def _g2a_url_slug_part(url: str) -> str:
    """Product path from G2A URL without product id suffix."""
    match = re.search(r"g2a\.com/pl/([^?]+)", url or "", re.I)
    if not match:
        return ""
    path = re.sub(r"-i\d+$", "", match.group(1), flags=re.I)
    return path.replace("-", " ")


def _g2a_token_keys(token: str) -> set[str]:
    """Index keys for a token — full form plus 6-char prefix for PL/EN title variants."""
    keys = {token}
    if len(token) >= 6:
        keys.add(token[:6])
    return keys


def _g2a_tokens_fuzzy_equal(a: str, b: str) -> bool:
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5:
        return False
    if a[:6] == b[:6]:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if len(shorter) >= 7 and longer.startswith(shorter[:6]):
        return True
    return False


def _g2a_row_tokens(name: str, url: str) -> set[str]:
    tokens = _g2a_significant_tokens(name)
    tokens |= _g2a_significant_tokens(_g2a_url_slug_part(url))
    return tokens


def _g2a_short_title_overlap(query: str, game_slug: str, name: str, url: str) -> float:
    """All significant query tokens must appear in the feed row (F1 + 25, GTA + v)."""
    sig = _g2a_significant_tokens(query, _normalize_game_slug(game_slug).replace("-", " "))
    if not sig:
        return 0.0
    row_sig = _g2a_row_tokens(name, url)
    if not row_sig:
        return 0.0
    matched = 0
    for qt in sig:
        if qt in row_sig or any(_g2a_tokens_fuzzy_equal(qt, ct) for ct in row_sig):
            matched += 1
    if matched < len(sig):
        return 0.0
    return matched / len(sig)


def _g2a_title_overlap(query: str, game_slug: str, name: str, url: str) -> float:
    """Token overlap with fuzzy prefix matching (PL title vs EN feed row)."""
    if _is_short_g2a_title(query, game_slug):
        short = _g2a_short_title_overlap(query, game_slug, name, url)
        if short >= MIN_MATCH_SCORE:
            return short

    slug = _normalize_game_slug(game_slug)
    q = _g2a_significant_tokens(query, slug.replace("-", " "))
    c = _g2a_row_tokens(name, url)
    if not q or not c:
        return 0.0

    matched = 0
    for qt in q:
        expanded = {qt} | _g2a_alias_tokens(qt)
        if any(
            _g2a_tokens_fuzzy_equal(alias, ct) for alias in expanded for ct in c
        ):
            matched += 1
    overlap = matched / len(q)

    slug_tokens = _g2a_significant_tokens(slug.replace("-", " "))
    url_tokens = _g2a_significant_tokens(_g2a_url_slug_part(url))
    if slug_tokens and url_tokens:
        url_matched = sum(
            1 for t in slug_tokens if any(_g2a_tokens_fuzzy_equal(t, u) for u in url_tokens)
        )
        overlap = max(overlap, url_matched / len(slug_tokens) * 0.95)

    q_slug = slugify(query)
    name_slug = slugify(name)
    url_slug = slugify(_g2a_url_slug_part(url))
    if q_slug and (q_slug in name_slug or q_slug in url_slug or name_slug in q_slug):
        overlap += 0.35
    return min(overlap, 1.0)


def _build_g2a_row_index(rows: list["_FeedRow"]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        for token in _g2a_row_tokens(row.name, row.url):
            for key in _g2a_token_keys(token):
                index.setdefault(key, []).append(idx)
    return index


def _g2a_query_token_keys(query: str, game_slug: str) -> list[str]:
    slug = _normalize_game_slug(game_slug)
    raw = sorted(_g2a_significant_tokens(query, slug.replace("-", " ")), key=len, reverse=True)
    keys: list[str] = []
    seen: set[str] = set()
    for token in raw:
        for alias in _g2a_alias_tokens(token):
            for key in _g2a_token_keys(alias):
                if key not in seen:
                    seen.add(key)
                    keys.append(key)
    for token in raw:
        for key in _g2a_token_keys(token):
            if key not in seen:
                seen.add(key)
                keys.append(key)
    return keys[:10]


def _g2a_candidate_row_indices(
    query: str, game_slug: str, index: dict[str, list[int]]
) -> set[int]:
    tokens = _g2a_query_token_keys(query, game_slug)
    if not tokens:
        return set()

    if _is_short_g2a_title(query, game_slug):
        sig = sorted(_g2a_significant_tokens(query, _normalize_game_slug(game_slug).replace("-", " ")))
        lists = [set(index.get(token, [])) for token in sig if index.get(token)]
        if len(lists) >= 2:
            candidates = lists[0]
            for chunk in lists[1:]:
                candidates &= chunk
            if candidates:
                return candidates
        if len(lists) == 1:
            return lists[0]

    candidates: set[int] = set()
    for token in tokens[:5]:
        candidates.update(index.get(token, []))

    if not candidates:
        return set()

    if len(candidates) > 2500:
        strong = [t for t in tokens if len(t) >= 5][:3]
        narrowed: set[int] | None = None
        for token in strong:
            chunk = set(index.get(token, []))
            if not chunk:
                continue
            narrowed = chunk if narrowed is None else (narrowed & chunk)
            if narrowed and len(narrowed) <= 800:
                break
        if narrowed:
            candidates = narrowed

    return candidates

def _g2a_feed_row_ok(name: str, url: str) -> bool:
    blob = f"{name} {url}".lower()
    return not any(marker in blob for marker in _G2A_FEED_SKIP)


def _g2a_number_tokens(*parts: str) -> set[str]:
    nums: set[str] = set()
    for part in parts:
        for token in slugify(part).split("-"):
            if token.isdigit():
                nums.add(token)
    return nums


_G2A_SHORT_TITLE_SKIP = (
    "season pack",
    "iconic edition",
    "bundle",
    "upgrade",
    "starter pack",
    "shark card",
    "expansion pass",
)


def _score_g2a_feed_row(name: str, url: str, query: str, game_slug: str) -> float:
    if not _g2a_feed_row_ok(name, url):
        return 0.0
    query_nums = _g2a_number_tokens(query, _normalize_game_slug(game_slug).replace("-", " "))
    row_nums = _g2a_number_tokens(name, _g2a_url_slug_part(url))
    if query_nums and (not row_nums or not (query_nums & row_nums)):
        return 0.0
    blob = f"{name} {url}".lower()
    if (
        ("phantom edition" in blob or "phantom-edition" in blob)
        and "phantom" not in (query or "").lower()
        and "phantom" not in (game_slug or "").lower()
    ):
        return 0.0
    score = _g2a_title_overlap(query, game_slug, name, url)
    if score < MIN_MATCH_SCORE:
        score = title_match_score(query, name)
    if score < MIN_MATCH_SCORE:
        slug = _normalize_game_slug(game_slug)
        score = title_match_score(slug.replace("-", " "), name)
    if score < MIN_MATCH_SCORE:
        return 0.0
    if any(marker in blob for marker in _G2A_FEED_PREFER):
        score += 0.15
    if _is_short_g2a_title(query, game_slug):
        q_low = (query or "").lower()
        if any(marker in blob for marker in _G2A_SHORT_TITLE_SKIP):
            if not any(marker.split()[0] in q_low for marker in _G2A_SHORT_TITLE_SKIP):
                score -= 0.35
        if name.strip().lower().startswith((query or "").strip().lower()):
            score += 0.1
    if "ultimate-edition" in blob and "ultimate" not in game_slug:
        score -= 0.15
    if "phantom-liberty" in blob and "phantom" not in game_slug:
        score -= 0.2
    if "dlc" in blob and "dlc" not in game_slug and "dlc" not in query.lower():
        score -= 0.25
    return score


def _build_row_index(rows: list["_FeedRow"]) -> dict[str, list[int]]:
    index: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        for token in _index_tokens(row.name):
            index.setdefault(token, []).append(idx)
    return index


def _candidate_row_indices(query: str, game_slug: str, index: dict[str, list[int]]) -> set[int]:
    tokens = sorted(_index_tokens(query, game_slug.replace("-", " ")), key=len, reverse=True)[:4]
    if not tokens:
        return set()

    lists = [index.get(token) for token in tokens if index.get(token)]
    if not lists:
        return set()

    candidates: set[int] | None = None
    for postings in sorted(lists, key=len):
        chunk = set(postings)
        if candidates is None:
            candidates = chunk
            continue
        narrowed = candidates & chunk
        if narrowed:
            candidates = narrowed
        if candidates and len(candidates) <= 400:
            break

    if candidates:
        return candidates
    return set(lists[0])


def _rows_to_csv_text(rows: list["_FeedRow"]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["product_name", "url", "price", "currency", "availability"])
    for row in rows:
        writer.writerow(
            [
                row.name,
                row.url,
                row.price_raw,
                row.currency,
                "in stock" if row.in_stock else "out of stock",
            ]
        )
    return buf.getvalue()


def _xml_child_text(elem: ET.Element, tag: str) -> str:
    for child in elem:
        if child.tag.lower() == tag.lower():
            return (child.text or "").strip()
    return ""


def _parse_g2a_xml(data: bytes) -> list[_FeedRow]:
    rows: list[_FeedRow] = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        logger.warning("G2A feed XML parse error: %s", exc)
        return rows

    for elem in root.iter():
        if elem.tag.lower() != "products":
            continue
        name = _xml_child_text(elem, "Name")
        url = _xml_child_text(elem, "URL")
        if not name or not url:
            continue
        if not _g2a_feed_row_ok(name, url):
            continue
        price = _parse_price(_xml_child_text(elem, "Price"))
        if price is None:
            continue
        currency = (_xml_child_text(elem, "Currency") or "PLN").upper()[:3]
        availability = _xml_child_text(elem, "Availability")
        if availability and not _parse_bool(availability):
            continue
        rows.append(
            _FeedRow(name=name, url=url, price_raw=price, currency=currency, in_stock=True)
        )
    return rows


_GAMIVO_SAFE_REGION_MARKERS = {
    "global",
    "worldwide",
    "ww",
    "eu",
    "europe",
    "european",
    "emea",
    "pl",
    "poland",
    "polska",
    "row",
}

_GAMIVO_BAD_PLATFORM_MARKERS = (
    "xbox",
    "playstation",
    "ps4",
    "ps5",
    "nintendo",
    "switch",
    "meta quest",
)

_GAMIVO_FEED_SKIP_MARKERS = (
    " account",
    "steam account",
    " gift",
    "gift card",
    "steam gift",
    "altergift",
    " dlc",
    " expansion",
    " add-on",
    " addon",
    " season pass",
    " soundtrack",
    " starter pack",
    " skin pack",
    " weapon pack",
    " upgrade pack",
    " points",
    " coins",
    " currency",
    " subscription",
    " membership",
)


def _is_safe_gamivo_region(region: str, title: str) -> bool:
    blob = f" {region} {title} ".lower()
    if not region.strip():
        return False
    if is_restricted_region_listing(blob):
        return False
    tokens = set(slugify(region).split("-")) | set(slugify(title).split("-"))
    return bool(tokens & _GAMIVO_SAFE_REGION_MARKERS)


def _gamivo_feed_row_ok(name: str, url: str, region: str, platform: str) -> bool:
    blob = f" {name} {url} {region} {platform} ".lower()
    if not _is_safe_gamivo_region(region, name):
        return False
    if any(marker in blob for marker in _GAMIVO_BAD_PLATFORM_MARKERS):
        return False
    if any(marker in blob for marker in _GAMIVO_FEED_SKIP_MARKERS):
        return False
    return True


def _parse_gamivo_xml(data: bytes) -> list[_FeedRow]:
    rows: list[_FeedRow] = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        logger.warning("Gamivo feed XML parse error: %s", exc)
        return rows

    for elem in root.iter():
        if elem.tag.lower() != "item":
            continue
        name = _xml_child_text(elem, "title")
        url = _xml_child_text(elem, "link")
        if not name or not url:
            continue
        availability = _xml_child_text(elem, "availability")
        if availability and not _parse_bool(availability):
            continue
        region = _xml_child_text(elem, "region")
        platform = _xml_child_text(elem, "activation_platform")
        if not _gamivo_feed_row_ok(name, url, region, platform):
            continue

        price_text = _xml_child_text(elem, "price")
        price = _parse_price(price_text)
        if price is None:
            continue
        currency_match = re.search(r"\b([A-Z]{3})\b", price_text.upper())
        currency = (currency_match.group(1) if currency_match else "PLN")[:3]
        rows.append(
            _FeedRow(name=name, url=url, price_raw=price, currency=currency, in_stock=True)
        )
    return rows


def _parse_feed_bytes(data: bytes, *, shop: str = "") -> list[_FeedRow]:
    if data.lstrip()[:1] == b"<":
        if shop == "Gamivo":
            return _parse_gamivo_xml(data)
        return _parse_g2a_xml(data)
    return _parse_csv(_decompress_csv(data))


def _read_cache_rows(shop: str) -> list[_FeedRow]:
    cache = _cache_path(shop)
    if not cache.is_file():
        return []
    return _parse_csv(cache.read_text(encoding="utf-8", errors="replace"))


def _get_shop_rows_indexed(shop: str) -> tuple[list[_FeedRow], dict[str, list[int]]]:
    cache = _cache_path(shop)
    mtime = cache.stat().st_mtime if cache.is_file() else 0.0
    cached = _SHOP_ROWS_CACHE.get(shop)
    if cached and cached[0] == mtime:
        return cached[1], cached[2]

    rows = _read_cache_rows(shop)
    index = _build_g2a_row_index(rows) if shop == "G2A" else _build_row_index(rows)
    _SHOP_ROWS_CACHE[shop] = (mtime, rows, index)
    return rows, index


def _parse_bool(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return text in ("1", "true", "yes", "in stock", "instock")


def _parse_price(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        price = float(re.sub(r"[^\d.]", "", text) or text)
    except ValueError:
        return None
    return price if price > 0 else None


def _row_to_feed_row(row: dict[str, str]) -> _FeedRow | None:
    lowered = {str(k).strip().lower(): (v or "").strip() for k, v in row.items()}
    name = (
        lowered.get("product_name")
        or lowered.get("title")
        or lowered.get("name")
        or ""
    )
    url = (
        lowered.get("aw_deep_link")
        or lowered.get("deep_link")
        or lowered.get("link")
        or lowered.get("url")
        or ""
    )
    if not name or not url:
        return None

    currency = (lowered.get("currency") or "PLN").upper()[:3]
    price = _parse_price(lowered.get("search_price") or lowered.get("store_price") or lowered.get("price"))
    if price is None:
        return None

    in_stock_raw = lowered.get("in_stock") or lowered.get("stock_status") or lowered.get("availability")
    in_stock = _parse_bool(in_stock_raw) if in_stock_raw else True
    if not in_stock:
        return None

    return _FeedRow(name=name, url=url, price_raw=price, currency=currency, in_stock=True)


def _price_pln(row: _FeedRow) -> float | None:
    if row.currency == "PLN":
        return round(row.price_raw, 2)
    converted = to_pln(row.price_raw, row.currency)
    if converted is not None:
        return round(converted, 2)
    return money_to_pln(row.price_raw, row.currency, minor_units=False)


def _feed_id(shop: str) -> str | None:
    env_key = f"AWIN_FEED_FID_{shop.upper().replace(' ', '_')}"
    fid = os.environ.get(env_key, "").strip()
    return fid or None


def _download_bytes(url: str) -> tuple[bytes | None, str | None]:
    timeout = 180 if "product-feeder.g2a.com" in url else 45
    try:
        response = requests.get(url, timeout=timeout, allow_redirects=True)
    except Exception as exc:
        logger.warning("affiliate feed download failed %s: %s", url[:80], exc)
        return None, str(exc)
    if response.status_code != 200:
        body = (response.text or "").strip()[:500]
        logger.warning(
            "affiliate feed HTTP %s for %s: %s",
            response.status_code,
            response.url[:100],
            body,
        )
        return None, body or f"HTTP {response.status_code}"
    return response.content, None


def _decompress_csv(data: bytes) -> str:
    if data[:2] == b"\x1f\x8b":
        return gzip.decompress(data).decode("utf-8", errors="replace")
    return data.decode("utf-8", errors="replace")


def _parse_csv(text: str) -> list[_FeedRow]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[_FeedRow] = []
    for raw in reader:
        parsed = _row_to_feed_row(raw)
        if parsed:
            rows.append(parsed)
    return rows


def _parse_feed_catalog_csv(text: str) -> list[FeedCatalogEntry]:
    if not text.strip() or text.lstrip().startswith("<"):
        return []
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []

    header = [c.strip().lower() for c in rows[0]]
    entries: list[FeedCatalogEntry] = []
    start = 1 if any("feed" in c or "advertiser" in c or "merchant" in c for c in header) else 0

    for row in rows[start:]:
        if not row or len(row) < 5:
            continue
        if start == 1:
            data = {header[i]: (row[i] if i < len(row) else "") for i in range(len(header))}
            adv_id = (
                data.get("advertiser id")
                or data.get("merchant id")
                or data.get("advertiser_id")
                or ""
            ).strip()
            name = (data.get("advertiser name") or data.get("advertiser") or "").strip()
            join_status = (data.get("join status") or data.get("membership") or "").strip()
            feed_id = (data.get("feed id") or data.get("fid") or "").strip()
            download_url = ""
            for key, val in data.items():
                if "url" in key and val.strip().startswith("http"):
                    download_url = val.strip()
                    break
        else:
            adv_id = row[0].strip()
            name = row[1].strip() if len(row) > 1 else ""
            join_status = row[3].strip() if len(row) > 3 else ""
            feed_id = row[4].strip() if len(row) > 4 else ""
            download_url = ""
            for cell in row:
                if cell.strip().startswith("http"):
                    download_url = cell.strip()
                    break

        if not adv_id or not feed_id:
            continue
        entries.append(
            FeedCatalogEntry(
                advertiser_id=adv_id,
                advertiser_name=name,
                join_status=join_status,
                feed_id=feed_id,
                download_url=download_url or None,
            )
        )
    return entries


def _fetch_feed_catalog(*, force: bool = False) -> tuple[list[FeedCatalogEntry], str | None]:
    global _catalog_cache
    now = time.time()
    if not force and _catalog_cache and now - _catalog_cache[0] < _CATALOG_TTL_SEC:
        return _catalog_cache[1], _catalog_cache[2]

    key = _awin_api_key()
    if not key:
        return [], "AWIN_DATAFEED_API_KEY not set"

    list_url = f"{_AWIN_LIST_BASE}/{key}"
    try:
        response = requests.get(list_url, timeout=120, allow_redirects=True)
    except Exception as exc:
        err = f"feed list request failed: {exc}"
        _catalog_cache = (now, [], err)
        return [], err

    if response.status_code != 200:
        body = (response.text or "").strip()[:300]
        err = f"feed list HTTP {response.status_code}: {body}"
        _catalog_cache = (now, [], err)
        return [], err

    entries = _parse_feed_catalog_csv(response.text)
    _catalog_cache = (now, entries, None)
    return entries, None


def _catalog_entry_for_merchant(merchant_id: str) -> FeedCatalogEntry | None:
    entries, _ = _fetch_feed_catalog()
    for entry in entries:
        if entry.advertiser_id == str(merchant_id):
            return entry
    return None


def _is_joined(entry: FeedCatalogEntry | None) -> bool:
    if entry is None:
        return False
    status = entry.join_status.lower()
    return "not joined" not in status and status not in ("", "rejected", "declined", "suspended")


def _awin_fid_download_url(feed_id: str) -> str:
    key = _awin_api_key()
    cols = quote(_CSV_COLUMNS, safe=",")
    return (
        f"{_AWIN_DOWNLOAD_BASE}/{key}/fid/{feed_id}/format/csv/"
        f"language/en/delimiter/%2C/compression/gzip/adultcontent/1/columns/{cols}/"
    )


def _awin_legacy_mid_download_url(merchant_id: str) -> str:
    key = _awin_api_key()
    cols = quote(_CSV_COLUMNS, safe=",")
    return (
        f"{_AWIN_LEGACY_DOWNLOAD_BASE}/{key}/mid/{merchant_id}/format/csv/"
        f"compression/gzip/columns/{cols}/"
    )


def _resolve_download_url(shop: str) -> tuple[str | None, str]:
    custom = _custom_feed_url(shop)
    if custom:
        return custom, "custom_url"

    fid = _feed_id(shop)
    if fid:
        return _awin_fid_download_url(fid), f"awin_fid_{fid}"

    mid = _merchant_id(shop)
    if mid:
        entry = _catalog_entry_for_merchant(mid)
        if entry and _is_joined(entry):
            if entry.download_url and _awin_api_key() in entry.download_url:
                return entry.download_url, f"awin_catalog_url_fid_{entry.feed_id}"
            return _awin_fid_download_url(entry.feed_id), f"awin_catalog_fid_{entry.feed_id}"
        if entry and not _is_joined(entry):
            return None, f"not_joined:{entry.advertiser_name or mid}"
        # The legacy mid download endpoint was decommissioned by Awin and now
        # returns HTTP 400 ("fid parameter is required"). Skip instead of
        # hammering a dead endpoint on every lookup; set AWIN_FEED_FID_<SHOP>
        # to restore this shop's feed once its feed id is known.
        return None, f"awin_mid_no_fid_{mid}"

    return None, "not_configured"


def _resolve_download_urls(shop: str) -> tuple[list[tuple[str, str]], str]:
    custom_urls = _custom_feed_urls(shop)
    if custom_urls:
        return [(url, f"custom_url_{idx}") for idx, url in enumerate(custom_urls, start=1)], "custom_url"

    url, source = _resolve_download_url(shop)
    if url:
        return [(url, source)], source
    return [], source


def _load_cached_shop_rows(shop: str) -> list[_FeedRow]:
    """Read feed rows from on-disk cache only (no network). Used during scans."""
    rows, _ = _get_shop_rows_indexed(shop)
    return rows


def _load_shop_rows(shop: str, *, force: bool = False) -> list[_FeedRow]:
    cache = _cache_path(shop)
    if not force and cache.is_file():
        age = time.time() - cache.stat().st_mtime
        if age < _CACHE_TTL_SEC:
            return _read_cache_rows(shop)

    urls, source = _resolve_download_urls(shop)
    if not urls:
        _last_download_errors[shop] = source
        return _read_cache_rows(shop) if cache.is_file() else []

    rows: list[_FeedRow] = []
    errors: list[str] = []
    for url, url_source in urls:
        data, err = _download_bytes(url)
        if not data:
            errors.append(err or url_source)
            continue
        rows.extend(_parse_feed_bytes(data, shop=shop))

    if not rows:
        _last_download_errors[shop] = "; ".join(errors) or source
        if cache.is_file():
            logger.info("affiliate feed %s: using stale cache (%s)", shop, _last_download_errors[shop])
            return _read_cache_rows(shop)
        return []

    _last_download_errors.pop(shop, None)
    if rows:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(_rows_to_csv_text(rows), encoding="utf-8")
        _SHOP_ROWS_CACHE.pop(shop, None)
        logger.info("affiliate feed %s: cached %s rows (%s)", shop, len(rows), source)
    return rows


def refresh_affiliate_feeds(*, force: bool = True) -> dict[str, int]:
    """Download/cache feeds for all configured shops. Run from cron."""
    if _awin_api_key():
        _fetch_feed_catalog(force=force)
    counts: dict[str, int] = {}
    for shop in ("G2A", "Kinguin", "CDKeys", "Gamivo", "Eneba", "Fanatical"):
        if not _custom_feed_urls(shop) and not (_merchant_id(shop) and _awin_api_key()):
            continue
        counts[shop] = len(_load_shop_rows(shop, force=force))
    return counts


def _affiliate_feed_lookup_once(
    shop: str,
    query: str,
    game_slug: str,
    rows: list[_FeedRow],
    index: dict[str, list[int]],
    *,
    threshold: float,
) -> FeedMatch | None:
    source = "g2a_feed" if shop == "G2A" else "gamivo_feed" if shop == "Gamivo" else "awin_feed"
    indices = (
        _g2a_candidate_row_indices(query, game_slug, index)
        if shop == "G2A" and index
        else _candidate_row_indices(query, game_slug, index)
        if index
        else set()
    )
    if not indices and index:
        if shop == "G2A":
            keys = _g2a_query_token_keys(query, game_slug)
            if keys:
                indices = set(index.get(keys[0], []))
        else:
            tokens = sorted(_index_tokens(query, game_slug.replace("-", " ")), key=len, reverse=True)
            if tokens:
                indices = set(index.get(tokens[0], []))

    best: FeedMatch | None = None
    best_score = 0.0
    for idx in indices:
        row = rows[idx]
        if shop == "G2A":
            score = _score_g2a_feed_row(row.name, row.url, query, game_slug)
        else:
            score = title_match_score(query, row.name)
        if score < threshold:
            continue
        if shop != "G2A":
            verdict = classify_keyshop_product(query, row.name, row.url, min_score=threshold)
            if not verdict["valid"]:
                continue
            if _is_opaque_awin_url(row.url) and score < _OPAQUE_AWIN_MIN_SCORE:
                continue
        price = _price_pln(row)
        if price is None or price <= 0:
            continue
        if score > best_score:
            best_score = score
            url = make_affiliate_link(row.url, shop)
            best = FeedMatch(
                url=_url_with_feed_title(url, row.name),
                price_pln=price,
                confidence=score,
                source=source,
                product_title=row.name,
            )
    return best


def affiliate_feed_lookup(
    shop: str,
    query: str,
    game_slug: str,
    *,
    min_score: float | None = None,
) -> FeedMatch | None:
    """Find best feed row for a game title. Returns None if feed unavailable."""
    if not _custom_feed_urls(shop) and not (_merchant_id(shop) and _awin_api_key()):
        return None

    rows, index = _get_shop_rows_indexed(shop)
    if not rows:
        rows = _load_shop_rows(shop)
        if rows:
            index = _build_g2a_row_index(rows) if shop == "G2A" else _build_row_index(rows)
            cache = _cache_path(shop)
            mtime = cache.stat().st_mtime if cache.is_file() else 0.0
            _SHOP_ROWS_CACHE[shop] = (mtime, rows, index)
    if not rows:
        return None

    threshold = min_score if min_score is not None else MIN_MATCH_SCORE
    if shop == "G2A":
        best: FeedMatch | None = None
        for q, slug in _g2a_lookup_variants(query, game_slug):
            match = _affiliate_feed_lookup_once(
                shop, q, slug, rows, index, threshold=threshold
            )
            if match and (best is None or match.confidence > best.confidence):
                best = match
        return best

    return _affiliate_feed_lookup_once(
        shop, query, game_slug, rows, index, threshold=threshold
    )


def affiliate_feed_status() -> dict[str, Any]:
    catalog, catalog_error = _fetch_feed_catalog()
    out: dict[str, Any] = {
        "awin_configured": bool(_awin_api_key()),
        "catalog_feeds": len(catalog),
        "catalog_error": catalog_error,
        "shops": {},
    }
    for shop in ("G2A", "Kinguin", "CDKeys", "Gamivo", "Eneba", "Fanatical"):
        mid = _merchant_id(shop)
        entry = _catalog_entry_for_merchant(mid) if mid else None
        cache = _cache_path(shop)
        out["shops"][shop] = {
            "merchant_id": mid,
            "feed_id": _feed_id(shop) or (entry.feed_id if entry else None),
            "joined": _is_joined(entry) if entry else None,
            "custom_url": bool(_custom_feed_url(shop)),
            "cache_rows": len(_read_cache_rows(shop)) if cache.is_file() else 0,
            "cache_age_sec": int(time.time() - cache.stat().st_mtime) if cache.is_file() else None,
            "last_error": _last_download_errors.get(shop),
        }
    return out
