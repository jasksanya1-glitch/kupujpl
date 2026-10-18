"""Shared helpers for key marketplaces (Eneba, Kinguin, CDKeys, G2A)."""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Callable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.core.affiliate import make_affiliate_link
from app.core.db_retry import commit_with_retry
from app.core.offer_verification import record_attempt, record_verified_price
from app.models.models import Game, Offer
from app.parsers.currency_pln import money_to_pln, to_pln

logger = logging.getLogger("keyshop_common")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/",
}

SHOP_HTTP_PROXY = os.environ.get("SHOP_HTTP_PROXY", "").strip() or None
_FETCH_TIMEOUT = int(os.environ.get("HTTP_FETCH_TIMEOUT", "20"))
MIN_MATCH_SCORE = float(os.environ.get("OFFER_MIN_MATCH_SCORE", "0.45"))

SKIP_PRODUCT_MARKERS = (
    "dlc",
    "expansion",
    "soundtrack",
    " artbook",
    " account",
    "steam account",
    "redkit",
    " add-on",
    " addon",
    " season pass",
    " coin ",
    " credits",
    " currency",
    "costume",
    "outfit",
    " skin",
    "skin pack",
    "hero skin",
    "character skin",
    "starter pack",
    "subscription",
    "membership",
    "voucher",
    "weapon pack",
    "upgrade pack",
    "pre-order bonus",
    " preorder bonus",
    "bundle only",
    " soundtrack",
    "phantom liberty",
)

DLC_MARKERS = (
    "dlc",
    "expansion",
    " add-on",
    " addon",
    " pack",
    "bundle",
    "season pass",
    "costume",
    "outfit",
    "skin",
    "soundtrack",
    "upgrade",
)

_TOKEN_STOP = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "for",
    "to",
    "in",
    "on",
    "pc",
    "game",
    "games",
    "edition",
    "global",
    "pl",
    "key",
    "cd",
    "steam",
    "gog",
    "gogcom",
    "com",
    "epic",
    "epicgames",
    "origin",
    "ea",
    "app",
    "eaapp",
    "ubisoft",
    "connect",
    "rockstar",
    "frontier",
    "digital",
    "download",
    "dowload",
    "code",
    "windows",
    "mac",
    "linux",
    "eu",
    "europe",
    "row",
    "ww",
    "worldwide",
    "emea",
    "language",
    "only",
    "en",
    "standard",
    "gift",
    # Edition tokens intentionally NOT listed here — they must remain distinctive
    # so "Base Game" ≠ "Base Game Ultimate Edition".
    "icons",
    "iconic",
    "super",
    "citizen",
    "cultist",
    "mamba",
    "schumacher",
}

_ALLOWED_PRODUCT_EXTRAS = {
    "pc",
    "steam",
    "gog",
    "gogcom",
    "com",
    "epic",
    "epicgames",
    "origin",
    "ea",
    "app",
    "eaapp",
    "ubisoft",
    "connect",
    "rockstar",
    "frontier",
    "digital",
    "download",
    "dowload",
    "code",
    "key",
    "cd",
    "global",
    "eu",
    "europe",
    "row",
    "ww",
    "worldwide",
    "emea",
    "standard",
    "edition",
    "gift",
    # Do not treat deluxe/ultimate/goty as harmless extras — wrong SKU otherwise.
    "icons",
    "iconic",
    "super",
    "citizen",
    "cultist",
    "mamba",
    "schumacher",
    "language",
    "only",
    "en",
    "pl",
    "windows",
    "mac",
    "linux",
}



def _is_store_sku_token(token: str) -> bool:
    """Epic/store URL suffixes like '-02' or offer UUIDs — not product identity."""
    t = (token or "").lower()
    if not t:
        return False
    if re.fullmatch(r"0\d", t):
        return True
    if len(t) >= 16 and re.fullmatch(r"[0-9a-f]+", t):
        return True
    if t.endswith("generalaudience") or t.endswith("audience"):
        return True
    return False


def _distinctive_tokens(tokens: set[str]) -> set[str]:
    return {
        t
        for t in tokens
        if t not in _ALLOWED_PRODUCT_EXTRAS and not _is_store_sku_token(t)
    }


_EDITION_EXTRA_TOKENS = frozenset(
    {
        "deluxe",
        "ultimate",
        "complete",
        "special",
        "limited",
        "definitive",
        "gold",
        "goty",
        "anniversary",
        "enhanced",
        "collection",
        "collectors",
        "collector",
        "remastered",
        "remaster",
        "remake",
        "hd",
        "anthology",
        "bundle",
        "season",
        "pass",
        "legacy",
        "premium",
        "account",
    }
)

_EDITION_PHRASE_MARKERS = (
    "ultimate edition",
    "deluxe edition",
    "complete edition",
    "definitive edition",
    "gold edition",
    "goty",
    "game of the year",
    "season pass",
    "legacy edition",
    "premium edition",
    "collector",
    "remaster",
    "remake",
)

_ROMAN_EDITION = {
    "i": 1,
    "ii": 2,
    "iii": 3,
    "iv": 4,
    "v": 5,
    "vi": 6,
    "vii": 7,
    "viii": 8,
    "ix": 9,
    "x": 10,
}


def slugify(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("_", " ")
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text.strip("-") or "gra"


def _query_wants_dlc(query: str) -> bool:
    lower = (query or "").lower()
    patterns = (
        r"\bdlc\b",
        r"\bexpansion\b",
        r"\bseason\s*pass\b",
        r"\badd[\s-]?on\b",
        r"\bcontent\s*pack\b",
        r"\bweapon\s*pack\b",
        r"\bskin\s*pack\b",
        r"\bbonus\s*content\b",
        r"\bstory\s*quest\s*pack\b",
        r"\bdodatek\b",
        r"\bprzepustk\w*\s+sezonow\w*\b",
    )
    return any(re.search(pattern, lower) for pattern in patterns)


def _edition_numbers(title: str) -> set[int]:
    nums: set[int] = set()
    for token in slugify(title).split("-"):
        if token in _ROMAN_EDITION:
            nums.add(_ROMAN_EDITION[token])
        elif token.isdigit() and len(token) <= 2:
            # Skip zero-padded store SKU suffixes (Epic …-02); keep "2" / "10".
            if token.startswith("0") and len(token) == 2:
                continue
            value = int(token)
            if 1 <= value <= 20:
                nums.add(value)
    return nums


def _title_tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for token in slugify(value).split("-"):
        if not token or token in _TOKEN_STOP:
            continue
        if len(token) <= 1 and not token.isdigit():
            continue
        if token in _ROMAN_EDITION:
            tokens.add(str(_ROMAN_EDITION[token]))
        else:
            tokens.add(token)
            if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
                tokens.add(token[:-1])
    return tokens


def edition_markers_mismatch(query: str, candidate: str) -> bool:
    """True when candidate is a different edition/SKU than the catalog game title."""
    q = (query or "").lower()
    c = (candidate or "").lower()
    if not q or not c:
        return False
    for phrase in _EDITION_PHRASE_MARKERS:
        if phrase in c and phrase not in q:
            return True
    q_tokens = _title_tokens(query)
    c_tokens = _title_tokens(candidate)
    edition_extras = (c_tokens - q_tokens) & _EDITION_EXTRA_TOKENS
    if edition_extras and not (edition_extras & q_tokens):
        return True
    return False


def title_mismatch(query: str, candidate: str) -> bool:
    """Reject obvious wrong-game matches (sequel / remake / DLC without intent)."""
    q = (query or "").lower()
    c = (candidate or "").lower()
    if not q or not c:
        return True

    if not _query_wants_dlc(query):
        if any(marker in c for marker in DLC_MARKERS):
            if not any(marker in q for marker in DLC_MARKERS):
                return True

    if edition_markers_mismatch(query, candidate):
        return True

    q_tokens = _title_tokens(query)
    c_tokens = _title_tokens(candidate)
    if q_tokens and c_tokens and q_tokens <= c_tokens:
        extras = _distinctive_tokens(c_tokens - q_tokens)
        if extras:
            return True

    # Both sides have distinctive product tokens beyond a shared franchise core
    # → different games (Innocence ≠ Legacy ≠ Requiem). Require a non-empty
    # *word* core (not just "3") so PL↔EN localizations are not rejected.
    if q_tokens and c_tokens:
        shared_core = {
            t
            for t in _distinctive_tokens(q_tokens & c_tokens)
            if not (t.isdigit() and len(t) <= 2)
        }
        q_only = _distinctive_tokens(q_tokens - c_tokens)
        c_only = _distinctive_tokens(c_tokens - q_tokens)
        if shared_core and q_only and c_only:
            return True

    q_nums = _edition_numbers(query)
    c_nums = _edition_numbers(candidate)
    if q_nums and c_nums and not (q_nums & c_nums):
        return True
    if q_nums and not c_nums:
        q_slug = slugify(query)
        c_slug = slugify(candidate)
        if c_slug and (c_slug in q_slug or q_slug in c_slug):
            missing = set(q_slug.split("-")) - set(c_slug.split("-"))
            if missing and all(
                t in _ROMAN_EDITION or (t.isdigit() and len(t) <= 2 and 1 <= int(t) <= 20)
                for t in missing
            ):
                return True

    q_remake = "remake" in q or "remaster" in q
    c_remake = "remake" in c or "remaster" in c
    if q_remake and not c_remake and not re.search(r"\b20(2[4-9]|3\d)\b", c):
        return True
    if c_remake and not q_remake:
        return True

    if ("resident evil 4" in q or re.search(r"\bre\s*4\b", q) or "resident-evil-4" in slugify(q)):
        wrong = (
            "requiem",
            "village",
            "resident evil 2",
            "resident evil 3",
            "resident evil 5",
            "resident evil 6",
            "resident evil 7",
            "resident evil 8",
            "hd edition",
            "ultimate hd",
        )
        if any(term in c for term in wrong):
            return True
        if re.search(r"\b(re|resident)\s*[^4]", c) and "4" not in re.sub(r"remake", "", c):
            if "resident evil" in c and "4" not in c:
                return True

    return False


def slug_match_bonus(query: str, candidate: str) -> float:
    """Bonus when slugs align on full hyphen segments (not prefix: rust ≠ rusty-lake)."""
    q_slug = slugify(query)
    c_slug = slugify(candidate)
    if not q_slug or not c_slug:
        return 0.0
    if q_slug == c_slug:
        return 0.35
    q_parts = [p for p in q_slug.split("-") if p]
    c_parts = [p for p in c_slug.split("-") if p]
    if q_parts and all(part in c_parts for part in q_parts):
        return 0.35
    if c_parts and all(part in q_parts for part in c_parts):
        return 0.35
    return 0.0


def title_match_score(query: str, candidate: str) -> float:
    """Simple token overlap score for matching game titles."""
    if title_mismatch(query, candidate):
        return 0.0

    def tokens(value: str) -> set[str]:
        stop = {
            "the",
            "a",
            "an",
            "of",
            "and",
            "for",
            "pc",
            "game",
            "edition",
            "global",
            "pl",
            "key",
            "gog",
            "com",
            "gogcom",
            "steam",
        }
        out: set[str] = set()
        for t in slugify(value).split("-"):
            if not t or t in stop or len(t) <= 1:
                continue
            out.add(t)
            if t.endswith("s") and len(t) > 4 and not t.endswith("ss"):
                out.add(t[:-1])
        return out

    q = tokens(query)
    c = tokens(candidate)
    if not q or not c:
        return 0.0
    overlap = len(q & c) / len(q)
    overlap += slug_match_bonus(query, candidate)
    return overlap


def is_confident_match(query: str, candidate: str, *, min_score: float | None = None) -> tuple[bool, float]:
    threshold = MIN_MATCH_SCORE if min_score is None else min_score
    score = title_match_score(query, candidate)
    return score >= threshold, score


def should_skip_product_title(title: str) -> bool:
    lower = (title or "").lower()
    return any(marker in lower for marker in SKIP_PRODUCT_MARKERS)


BAD_KEYSHOP_PRODUCT_MARKERS = (
    " skin ",
    " account",
    " pet ",
    " badge",
    " collectible",
    " pin ",
    " points",
    " coin",
    " crown",
    " currency",
    " game time card",
    " subscription",
    " membership",
    " voucher",
    " starter pack",
    " meta quest",
    " xbox",
    " playstation",
    " ps4",
    " ps5",
    " nintendo",
    " switch",
    " vr ",
    " dlc ",
    " add on ",
    " add-on ",
    " expansion ",
    " gift ",
    " gift-",
    "-gift ",
    "-gift-",
    "steam gift",
    "steam-gift",
    "altergift",
    " chapter ",
    " weapon ",
    " xp boost",
)


def product_title_from_url(url: str) -> str:
    """Best-effort product title extraction from common keyshop URLs."""
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    path = (parsed.path or "").strip("/")
    for source in (parsed.fragment, parsed.query):
        params = parse_qs(source)
        for key in ("kp_title", "product_title", "title", "name"):
            for raw in params.get(key, []):
                title = unquote(raw or "").strip()
                if title:
                    return title
    if "awin1.com" in host or "awstrack.me" in host:
        fragment_params = parse_qs(parsed.fragment)
        for key in ("kp_title", "product_title", "title", "name"):
            for raw in fragment_params.get(key, []):
                title = unquote(raw or "").strip()
                if title:
                    return title
        params = parse_qs(parsed.query)
        for key in ("kp_title", "product_title", "title", "name"):
            for raw in params.get(key, []):
                title = unquote(raw or "").strip()
                if title:
                    return title
        for key in ("ued", "url", "desturl", "destination", "redirect", "p"):
            for raw in params.get(key, []):
                nested = unquote(raw or "")
                if nested.startswith(("http://", "https://")):
                    return product_title_from_url(nested)
    if not path:
        return ""
    if "instant-gaming.com" in host:
        match = re.search(r"/?pl/\d+-([^/?#]+)/?", parsed.path or "")
        if match:
            raw = match.group(1)
            raw = re.sub(r"-(pc|mac|game|steam|gog|epic|europe|global)$", "", raw, flags=re.I)
            return raw.replace("-", " ")
    part = path.rsplit("/", 1)[-1]
    part = part.split("?", 1)[0]
    part = re.sub(r"-i\d+$", "", part, flags=re.I)
    part = re.sub(r"-\d{5,}$", "", part)
    return part.replace("-", " ").replace("_", " ")


def _region_blob(text: str) -> str:
    decoded = unquote(text or "").lower()
    decoded = re.sub(r"[/_?&#=:+.%]+", " ", decoded)
    decoded = decoded.replace("-", " ")
    return re.sub(r"\s+", " ", f" {decoded} ")


_SAFE_REGION_PATTERN = re.compile(
    r"\b(pl|poland|polska|europe|european|eu|eea|emea|worldwide|global)\b"
)


_RESTRICTED_REGION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bnorth\s*america\b",
        r"\bna\b",
        r"\bcanada\b",
        r"\bca\b",
        r"\bunited\s*states\b",
        r"\busa\b",
        r"\bu\s+s\b",
        r"\bus\s*(?:only|region|steam|key|code|gift|account|activation|version)\b",
        r"\b(?:pc|steam|xbox|windows|key|code|gift)\s*us\b",
        r"\blatam\b",
        r"\blatin\s*america\b",
        r"\bargentina\b",
        r"\bbrazil\b",
        r"\bbr\b",
        r"\bturkey\b",
        r"\bturkiye\b",
        r"\btr\b",
        r"\brussia\b",
        r"\brussian\b",
        r"\bru\b",
        r"\bcis\b",
        r"\bbelarus\b",
        r"\bukraine\b",
        r"\buae\b",
        r"\bunited\s*arab\s*emirates\b",
        r"\bemirates\b",
        r"\bmiddle\s*east\b",
        r"\bmena\b",
        r"\bgcc\b",
        r"\bsaudi\b",
        r"\bqatar\b",
        r"\bkuwait\b",
        r"\bafrica\b",
        r"\bmea\b",
        r"\basia\b",
        r"\basian\b",
        r"\bapac\b",
        r"\bsea\b",
        r"\bsouth\s*east\s*asia\b",
        r"\bchina\b",
        r"\bchinese\b",
        r"\bkorea\b",
        r"\bindia\b",
        r"\bindonesia\b",
        r"\baustralia\b",
        r"\bau\b",
        r"\brow\s*only\b",
        r"\brest\s*of\s*world\s*only\b",
        r"\bglobal\s*except\b",
        r"\bworldwide\s*except\b",
        r"\bnot\s*(?:for|available\s*in|activat(?:e|ion)\s*in)\s*(?:eu|europe|pl|poland|polska)\b",
        r"\bregion\s*locked\b",
        r"\bregion\s*lock\b",
    )
)

_NA_REGION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\bnorth\s*america\b",
        r"\bna\b",
        r"\bcanada\b",
        r"\bca\b",
        r"\bunited\s*states\b",
        r"\busa\b",
        r"\bu\s+s\b",
        r"\bus\s*(?:only|region|steam|key|code|gift|account|activation|version)\b",
        r"\b(?:pc|steam|xbox|windows|key|code|gift)\s*us\b",
    )
)

_EU_ONLY_REGION_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"\beu\s*only\b",
        r"\beurope(?:an)?\s*only\b",
        r"\bpoland\s*only\b",
        r"\bpolska\s*only\b",
        r"\bpl\s*only\b",
        r"\b(?:eu|europe(?:an)?)\s*region\b",
        r"\bregion\s*(?:eu|europe(?:an)?)\b",
        r"\bactivat(?:e|ion)\s*(?:in\s*)?(?:eu|europe(?:an)?)\b",
        r"\b(?:eu|europe(?:an)?)\s*(?:key|steam|pc)\b",
        r"\bnot\s*(?:for|available\s*in|activat(?:e|ion)\s*in)\s*(?:us|usa|united\s*states|na|north\s*america)\b",
    )
)


_AMBIGUOUS_REGION_PATTERN = re.compile(
    r"\b(?:region|activation|activate|only|restricted|locked)\b"
)

_GLOBAL_REGION_MARKERS = (
    " global",
    " worldwide",
    " world wide",
    " ww ",
    "/ww/",
    "-ww-",
    " row ",
    "/row/",
    "-row-",
    "rest of world",
    "emea",
)

_BLOCKED_ONLY_REGION_MARKERS = (
    "latam",
    "argentina",
    "turkey",
    "turkiye",
    " ru ",
    "-ru-",
    "/ru/",
    " russia",
    " russian",
    " latin america",
    " asia",
    " asian",
    " pc au",
    " steam au",
    " australia",
    " pc tr",
    " steam tr",
    " mena",
    " middle east",
    " africa",
    "/cis",
    "-cis-",
    " sea ",
    "global except",
    "row only",
)


def detect_activation_region(text: str) -> str:
    """Return eu|na|global|unknown|blocked from listing title/url/region blob."""
    blob = f" {_region_blob(text)} "
    lower = f" {(text or '').lower()} "
    if any(m in lower for m in _BLOCKED_ONLY_REGION_MARKERS):
        return "blocked"
    if any(p.search(blob) for p in _RESTRICTED_REGION_PATTERNS):
        # Distinguish NA vs other restricted
        if any(p.search(blob) for p in _NA_REGION_PATTERNS) or any(m in lower for m in _NA_REGION_MARKERS):
            return "na"
        if any(p.search(blob) for p in _EU_ONLY_REGION_PATTERNS) or any(
            m in lower for m in _EU_ONLY_REGION_MARKERS
        ):
            return "eu"
        # LATAM / TR / RU / Asia etc.
        if not any(p.search(blob) for p in _NA_REGION_PATTERNS):
            return "blocked"
    if any(m in lower for m in _NA_REGION_MARKERS) or any(p.search(blob) for p in _NA_REGION_PATTERNS):
        return "na"
    if any(m in lower for m in _EU_ONLY_REGION_MARKERS) or any(
        p.search(blob) for p in _EU_ONLY_REGION_PATTERNS
    ):
        return "eu"
    if any(m in lower for m in _GLOBAL_REGION_MARKERS) or re.search(
        r"\b(?:global|worldwide|ww|row)\b", blob
    ):
        return "global"
    return "unknown"


def is_blocked_activation_region(text: str) -> bool:
    """True for keys that are neither EU nor NA nor Global (LATAM/RU/TR/Asia…)."""
    return detect_activation_region(text) == "blocked"


def classify_keyshop_product(
    game_title: str,
    product_title: str,
    url: str = "",
    *,
    min_score: float = 0.45,
) -> dict[str, object]:
    """Classify whether a keyshop product looks valid for a base game."""
    candidate = product_title or product_title_from_url(url)
    if not candidate:
        return {"valid": False, "reason": "no_candidate", "score": 0.0, "activation_region": "unknown"}
    text = f" {candidate.lower()} {url.lower()} "
    activation = detect_activation_region(text)
    if activation == "blocked":
        game_blob = _region_blob(game_title)
        listing_blob = _region_blob(text)
        matched_patterns = [
            pattern for pattern in _RESTRICTED_REGION_PATTERNS if pattern.search(listing_blob)
        ]
        # Allow if the base game title itself embeds the same region (rare)
        if not matched_patterns or not all(pattern.search(game_blob) for pattern in matched_patterns):
            return {
                "valid": False,
                "reason": "restricted_region",
                "score": 0.0,
                "activation_region": activation,
            }
        activation = "unknown"
    for marker in BAD_KEYSHOP_PRODUCT_MARKERS:
        if marker in text:
            if marker == " vr " and "vr" in (game_title or "").lower():
                continue
            if marker == " crown" and "crown" in (game_title or "").lower():
                continue
            if marker in (" dlc ", " expansion ", " add on ", " add-on ") and _query_wants_dlc(game_title):
                continue
            return {
                "valid": False,
                "reason": f"bad_marker:{marker.strip()}",
                "score": 0.0,
                "activation_region": activation,
            }
    if edition_markers_mismatch(game_title, candidate):
        return {
            "valid": False,
            "reason": "edition_mismatch",
            "score": 0.0,
            "activation_region": activation,
        }
    if title_mismatch(game_title, candidate):
        return {
            "valid": False,
            "reason": "title_mismatch",
            "score": 0.0,
            "activation_region": activation,
        }
    score = title_match_score(game_title, candidate)
    game_nums = _edition_numbers(game_title)
    cand_nums = _edition_numbers(candidate)
    if (game_nums or cand_nums) and game_nums != cand_nums:
        return {
            "valid": False,
            "reason": "edition_number_mismatch",
            "score": score,
            "activation_region": activation,
        }
    if score < min_score:
        return {
            "valid": False,
            "reason": "low_score",
            "score": score,
            "activation_region": activation,
        }
    return {
        "valid": True,
        "reason": "match",
        "score": score,
        "activation_region": activation if activation != "blocked" else "unknown",
    }


_RESTRICTED_REGION_MARKERS = (
    "latam",
    "argentina",
    "turkey",
    "turkiye",
    " ru ",
    "-ru-",
    "/ru/",
    " russia",
    " russian",
    " united states",
    " pc us",
    " steam us",
    " us steam",
    " us windows",
    " windows us",
    " xbox us",
    " latin america",
    " latam",
    " asia",
    " asian",
    " pc au",
    " steam au",
    " au steam",
    " xbox au",
    " australia",
    " pc tr",
    " steam tr",
    " tr steam",
    " pc fr",
    " steam fr",
    " fr steam",
    " pc de",
    " steam de",
    " de steam",
    " pc na",
    " steam na",
    " na steam",
    " mena",
    " middle east",
    " africa",
    "/cis",
    "-cis-",
    " sea ",
    "global except",
    "row only",
)

# NA markers are restricted for PL shoppers but allowed for US shopping region.
_NA_REGION_MARKERS = (
    " united states",
    " pc us",
    " steam us",
    " us steam",
    " us windows",
    " windows us",
    " xbox us",
    " pc na",
    " steam na",
    " na steam",
)

_EU_ONLY_REGION_MARKERS = (
    " eu only",
    " europe only",
    " european only",
    " poland only",
    " polska only",
    " pl only",
    " eu region",
    " europe region",
    " region eu",
    " region europe",
    " activation eu",
    " activation europe",
    " eu key",
    " europe key",
)


def is_restricted_region_listing(text: str, region: str = "pl") -> bool:
    """Skip region-locked keys for the given shopping region (default PL)."""
    shopping = (region or "pl").strip().lower() or "pl"
    lower = (text or "").lower()
    markers = _RESTRICTED_REGION_MARKERS
    patterns = _RESTRICTED_REGION_PATTERNS
    if shopping == "us":
        na_set = set(_NA_REGION_MARKERS)
        markers = tuple(m for m in _RESTRICTED_REGION_MARKERS if m not in na_set)
        markers = markers + _EU_ONLY_REGION_MARKERS
        na_src = {p.pattern for p in _NA_REGION_PATTERNS}
        patterns = tuple(p for p in _RESTRICTED_REGION_PATTERNS if p.pattern not in na_src)
        patterns = patterns + _EU_ONLY_REGION_PATTERNS
    if any(marker in lower for marker in markers):
        return True
    blob = _region_blob(text)
    if any(pattern.search(blob) for pattern in patterns):
        return True
    if _AMBIGUOUS_REGION_PATTERN.search(blob) and not _SAFE_REGION_PATTERN.search(blob):
        return True
    if shopping == "us" and _AMBIGUOUS_REGION_PATTERN.search(blob):
        if any(p.search(blob) for p in _EU_ONLY_REGION_PATTERNS):
            return True
        if re.search(r"\b(?:eu|europe|european|poland|polska)\b", blob) and not re.search(
            r"\b(?:us|usa|na|north\s*america|worldwide|global)\b", blob
        ):
            return True
    return False


try:
    from curl_cffi import requests as _cffi_requests

    _HAS_CFFI = True
except ImportError:
    _cffi_requests = None
    _HAS_CFFI = False


def fetch_url(url: str, *, timeout: int | None = None, prefer_cffi: bool = False) -> requests.Response | None:
    """GET with optional curl_cffi impersonation and proxy."""
    if timeout is None:
        timeout = _FETCH_TIMEOUT
    proxies = {"http": SHOP_HTTP_PROXY, "https": SHOP_HTTP_PROXY} if SHOP_HTTP_PROXY else None
    try:
        if prefer_cffi and _HAS_CFFI and _cffi_requests is not None:
            return _cffi_requests.get(
                url,
                headers=HEADERS,
                timeout=timeout,
                impersonate="chrome131",
                proxies=proxies,
            )
        return requests.get(url, headers=HEADERS, timeout=timeout, proxies=proxies)
    except Exception as exc:
        logger.debug("Fetch failed %s: %s", url, exc)
        return None


def _parse_visible_price(text: str) -> tuple[float, str] | None:
    for match in re.findall(r"(\d+[\.,]\d+)\s*(zł|zl|PLN|€|EUR)", text, re.IGNORECASE):
        try:
            amount = float(match[0].replace(",", "."))
        except ValueError:
            continue
        unit = match[1].lower()
        currency = "PLN" if unit in {"zł", "zl", "pln"} else "EUR"
        return amount, currency
    return None


def _parse_json_money(html: str) -> tuple[float, str] | None:
    best: tuple[float, str] | None = None
    for amount_str, currency in re.findall(
        r'"amount"\s*:\s*(\d+)\s*,\s*"currency"\s*:\s*"([A-Z]{3})"',
        html,
    ):
        try:
            amount = int(amount_str)
        except ValueError:
            continue
        pln = money_to_pln(amount, currency)
        if pln is None:
            continue
        if best is None or pln < best[0]:
            best = (pln, currency)
    return best


def _parse_kinguin_listing_price(html: str) -> tuple[float, str] | None:
    match = re.search(
        r'"lowestPrice"\s*:\s*(\d+(?:\.\d+)?)\s*,\s*"highestPrice"\s*:\s*(\d+(?:\.\d+)?)',
        html,
    )
    if not match:
        return None
    amount = float(match.group(1))
    return amount, "EUR"


def extract_best_price(html: str, *, kinguin_listing: bool = False) -> float | None:
    if kinguin_listing:
        parsed = _parse_kinguin_listing_price(html)
        if parsed:
            amount, currency = parsed
            return to_pln(amount, currency)
    parsed = _parse_json_money(html)
    if parsed:
        pln, _currency = parsed
        return pln
    visible = _parse_visible_price(html)
    if visible:
        amount, currency = visible
        return to_pln(amount, currency)
    return None


# Storefronts keyed by AppID / console catalog ID — title classify is optional.
_ID_BACKED_SHOPS = frozenset(
    {"Steam", "Steam US", "PlayStation Store", "Xbox Store"}
)
# Digi stores that still need title/URL classify (GOG Innocence≠Legacy, etc.).
_TITLE_MATCH_SHOPS = frozenset(
    {
        "GOG",
        "Epic Games",
        "Fanatical",
        "Humble Store",
        "Instant Gaming",
        "Kinguin",
        "G2A",
        "CDKeys",
        "Gamivo",
        "Eneba",
    }
)


def upsert_keyshop_offer(
    db: Session,
    game: Game,
    shop_name: str,
    product_url: str,
    price_pln: float,
    *,
    is_official: bool = False,
    match_confidence: float | None = None,
    activation_region: str | None = None,
    product_title: str | None = None,
    live_fetch: bool = True,
    observed_at: datetime | None = None,
) -> bool:
    region = (activation_region or "").strip().lower() or None
    # Permanent F2P base games: never attach paid marketplace / digi copies.
    if bool(getattr(game, "is_free", False)) and shop_name not in _ID_BACKED_SHOPS:
        if price_pln is not None and float(price_pln) > 0.01:
            logger.info(
                "Skipping paid %s offer for F2P game %s (%.2f)",
                shop_name,
                game.title,
                float(price_pln),
            )
            return False

    needs_title_match = shop_name in _TITLE_MATCH_SHOPS or (
        shop_name not in _ID_BACKED_SHOPS and shop_name != "Steam"
    )
    if needs_title_match:
        candidate = product_title or product_title_from_url(product_url)
        verdict = classify_keyshop_product(
            game.title,
            candidate,
            product_url,
            min_score=MIN_MATCH_SCORE,
        )
        # Official digi + Steam AppID: allow low fuzzy score for PL↔EN titles
        # when hard title_mismatch did not fire (no shared wrong franchise core).
        allow_localized = (
            is_official
            and bool(getattr(game, "steam_appid", None))
            and verdict.get("reason") == "low_score"
            and not title_mismatch(game.title, candidate or "")
        )
        if not verdict["valid"] and not allow_localized:
            logger.info(
                "Skipping %s offer for %s: %s (%s)",
                shop_name,
                game.title,
                verdict["reason"],
                product_url[:160],
            )
            # Soft-disable any existing row for this shop (any region) so bad
            # GOG/Epic matches cannot stay public after a failed re-check.
            stale = (
                db.query(Offer)
                .filter(Offer.game_id == game.id, Offer.shop_name == shop_name)
                .all()
            )
            for row in stale:
                row.in_stock = False
                if row.match_confidence is None or row.match_confidence > 0:
                    row.match_confidence = 0.0
                record_attempt(row, status="error", source="match_reject")
            return False
        if not region or region == "unknown":
            detected = str(verdict.get("activation_region") or "unknown")
            region = detected if detected != "blocked" else "unknown"
        if match_confidence is None:
            try:
                match_confidence = float(verdict.get("score") or 0.0)
            except (TypeError, ValueError):
                match_confidence = None
            if allow_localized and (match_confidence or 0) < MIN_MATCH_SCORE:
                match_confidence = float(MIN_MATCH_SCORE)
    elif shop_name in _ID_BACKED_SHOPS or is_official:
        if not region or region == "unknown":
            region = "na" if shop_name == "Steam US" else "global"

    if not region:
        region = "unknown"
    if region == "blocked":
        return False
    affiliate_url = make_affiliate_link(product_url, shop_name)
    existing = (
        db.query(Offer)
        .filter(
            Offer.game_id == game.id,
            Offer.shop_name == shop_name,
            Offer.activation_region == region,
        )
        .first()
    )
    # Migrate legacy single-row offers (no region awareness) into the tagged row
    if existing is None and region != "unknown":
        legacy = (
            db.query(Offer)
            .filter(
                Offer.game_id == game.id,
                Offer.shop_name == shop_name,
                Offer.activation_region == "unknown",
            )
            .first()
        )
        if legacy is not None:
            legacy.activation_region = region
            existing = legacy
    source = (shop_name or "keyshop").lower().replace(" ", "_")
    if existing:
        prev_price = float(existing.price_pln) if existing.price_pln is not None else None
        existing.affiliate_url = affiliate_url
        existing.activation_region = region
        if match_confidence is not None:
            existing.match_confidence = match_confidence
        if live_fetch:
            # Stamp only after a successful live source check (same price still counts).
            record_verified_price(
                existing,
                price_pln=float(price_pln),
                source=source,
                previous_price=prev_price,
                now=observed_at,
            )
        else:
            # Replay / import of cached rows: update price fields, never freshness.
            existing.price_pln = float(price_pln)
            existing.in_stock = True
            if observed_at is not None:
                existing.updated_at = observed_at
            record_attempt(existing, status="skipped", source=source)
        from app.core.price_history import record_offer_price_change

        db.flush()
        record_offer_price_change(
            db,
            game_id=game.id,
            shop_name=shop_name,
            price_pln=price_pln,
            previous_price=prev_price,
        )
        return True
    else:
        offer = Offer(
            game_id=game.id,
            shop_name=shop_name,
            activation_region=region,
            price_pln=price_pln,
            original_price_pln=None,
            affiliate_url=affiliate_url,
            is_official=is_official,
            in_stock=True,
            match_confidence=match_confidence,
        )
        db.add(offer)
        db.flush()
        if live_fetch:
            record_verified_price(
                offer,
                price_pln=float(price_pln),
                source=source,
                previous_price=None,
                now=observed_at,
            )
        else:
            record_attempt(offer, status="skipped", source=source)
        from app.core.price_history import record_offer_price_change

        record_offer_price_change(
            db,
            game_id=game.id,
            shop_name=shop_name,
            price_pln=price_pln,
            previous_price=None,
        )
        return True


def refresh_keyshop_for_game(
    db: Session,
    game: Game,
    shop_name: str,
    search_fn: Callable[[str, str], tuple[str | None, float | None]],
) -> bool:
    slug = slugify(game.title)
    product_url, price = search_fn(game.title, slug)
    if not product_url or price is None:
        return False
    return upsert_keyshop_offer(db, game, shop_name, product_url, price)


def import_keyshop_offers(
    db: Session,
    *,
    shop_name: str,
    search_fn: Callable[[str, str], tuple[str | None, float | None]],
    limit: int = 150,
    delay_sec: float = 2.5,
) -> dict:
    """Update offers for enriched games only (batch)."""
    import time

    games = (
        db.query(Game)
        .filter(Game.steam_enriched == True)
        .order_by(Game.id.desc())
        .limit(limit)
        .all()
    )

    added = updated = skipped = 0
    logger.info("Starting %s updates for %s games...", shop_name, len(games))

    for game in games:
        slug = slugify(game.title)
        product_url, price = search_fn(game.title, slug)
        if product_url and price is not None:
            had = (
                db.query(Offer)
                .filter(Offer.game_id == game.id, Offer.shop_name == shop_name)
                .first()
            )
            applied = upsert_keyshop_offer(db, game, shop_name, product_url, price)
            if applied:
                commit_with_retry(db)
                if had:
                    updated += 1
                else:
                    added += 1
            else:
                skipped += 1
        else:
            skipped += 1
        time.sleep(delay_sec)

    logger.info("%s import done: added=%s updated=%s skipped=%s", shop_name, added, updated, skipped)
    return {"shop": shop_name, "added": added, "updated": updated, "skipped": skipped}


# Legacy HTML search (kept for fallback; most shops are SPA now).
def search_keyshop_html(
    *,
    search_url: str,
    base_url: str,
    href_predicate: Callable[[str], bool],
    query: str,
    game_slug: str,
    keyword_count: int = 3,
) -> tuple[str | None, float | None]:
    response = fetch_url(search_url)
    if response is None:
        return None, None
    if response.status_code == 429:
        logger.warning("Rate limited (429) for %s", search_url)
        return None, None
    if response.status_code != 200:
        logger.warning("HTTP %s for %s", response.status_code, search_url)
        return None, None

    soup = BeautifulSoup(response.text, "html.parser")
    keywords = [k for k in game_slug.split("-")[:keyword_count] if k]
    if not keywords:
        keywords = slugify(query).split("-")[:keyword_count]

    best_price: float | None = None
    best_url: str | None = None

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "")
        if not href_predicate(href):
            continue
        if not all(kw in href.lower() for kw in keywords):
            continue

        container = anchor
        for _ in range(5):
            if container is None:
                break
            parsed = _parse_visible_price(container.get_text(" ", strip=True))
            if parsed is not None:
                amount, currency = parsed
                price = to_pln(amount, currency)
                if price is not None and (best_price is None or price < best_price):
                    best_price = price
                    best_url = urljoin(base_url, href)
            container = container.parent

    return best_url, best_price
