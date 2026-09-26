"""Deal Candidate Engine — detects price events; never auto-publishes articles.

Uses existing tables:
- offers: current price, original_price_pln, shop_name, in_stock, updated_at
- price_snapshots: KupujPL-observed history (from ~2026-07)
- games.lowest_ever_pln: maintained from observed data (not market all-time)
- free giveaways cache: ends_at when present (expiring_deal only)

Offers have no valid_until column — expiry candidates require giveaway ends_at.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.articles import create_draft_from_candidate
from app.models.models import Article, DiscoverCandidate, Game, Offer, PriceSnapshot

logger = logging.getLogger("discover_candidates")

COOLDOWN_HOURS = int(os.environ.get("DEAL_CANDIDATE_COOLDOWN_HOURS", "36"))
MIN_DISCOUNT_PCT = int(os.environ.get("DEAL_CANDIDATE_MIN_DISCOUNT", "50"))
MIN_ABS_DROP_PLN = float(os.environ.get("DEAL_CANDIDATE_MIN_ABS_DROP", "5"))
MIN_REL_DROP_PCT = float(os.environ.get("DEAL_CANDIDATE_MIN_REL_DROP", "10"))
HIST_MIN_SNAPSHOTS = int(os.environ.get("DEAL_CANDIDATE_HIST_MIN_SNAPS", "3"))
HIST_MIN_DAYS = int(os.environ.get("DEAL_CANDIDATE_HIST_MIN_DAYS", "7"))
SCAN_OFFER_HOURS = int(os.environ.get("DEAL_CANDIDATE_SCAN_HOURS", "48"))
# Editorial candidates require fresh offers — stale zeros (months old) are rejected.
MAX_OFFER_AGE_HOURS = int(os.environ.get("DEAL_CANDIDATE_MAX_OFFER_AGE_HOURS", "72"))
FREE_PREV_MIN = float(os.environ.get("DEAL_CANDIDATE_FREE_PREV_MIN", "1.0"))
# Same-shop paid evidence must be recent enough to look like a promo transition,
# not a permanent F2P storefront with one ancient paid scrape.
FREE_PRIOR_MAX_AGE_DAYS = int(os.environ.get("DEAL_CANDIDATE_FREE_PRIOR_MAX_DAYS", "45"))
FREE_MIN_SAME_SHOP_PAID_SNAPS = int(os.environ.get("DEAL_CANDIDATE_FREE_MIN_PAID_SNAPS", "2"))
MAX_LIST_PRICE_RATIO = float(os.environ.get("DEAL_CANDIDATE_MAX_LIST_RATIO", "20"))
# Same-shop prior drops denser than this look like SKU/mismatch noise (e.g. wrong GOG product).
MAX_SAME_SHOP_DROP_RATIO = float(os.environ.get("DEAL_CANDIDATE_MAX_PRIOR_DROP_RATIO", "12"))
# Same-shop prior selling price must be recent enough to prove a *current* sale
# (45d ≈ typical Steam/Epic sale cycle + scrape lag; older baselines are noise).
PRIOR_PROMO_MAX_AGE_DAYS = int(os.environ.get("DEAL_CANDIDATE_PRIOR_PROMO_MAX_DAYS", "45"))
POPULAR_REVIEW_MIN = int(os.environ.get("DEAL_CANDIDATE_POPULAR_REVIEWS", "5000"))
SCHEDULER_INTERVAL_SEC = int(os.environ.get("DEAL_CANDIDATE_INTERVAL_SEC", str(3600)))
# Default OFF for safe production rollout — enable explicitly after first manual scan.
SCHEDULER_ENABLED = os.environ.get("DEAL_CANDIDATE_SCHEDULER", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

SCORE_FREE = 50
SCORE_DISC_90 = 45
SCORE_DISC_80 = 40
SCORE_DISC_70 = 35
SCORE_DISC_50 = 25
SCORE_HIST_LOW = 30
SCORE_PRICE_DROP = 20
SCORE_EXPIRE_24 = 15
SCORE_EXPIRE_48 = 10
SCORE_POPULAR = 20
SCORE_CONF_HIGH = 10
SCORE_CONF_MEDIUM = 5

TYPE_FREE = "free_game"
TYPE_BIG = "big_discount"
TYPE_DROP = "price_drop"
TYPE_HIST = "historical_low"
TYPE_EXPIRE = "expiring_deal"

CONF_HIGH = "HIGH"
CONF_MEDIUM = "MEDIUM"
CONF_LOW = "LOW"
EDITORIAL_CONFIDENCE = frozenset({CONF_HIGH, CONF_MEDIUM})

_NON_FULL_GAME_TYPES = frozenset({"dlc", "demo", "mod", "music", "video", "series"})
_TITLE_REJECT_RE = re.compile(
    r"\b("
    r"dlc|demo|soundtrack|ost|bundle|pack(?!\s*edition)|"
    r"friend'?s?\s*pass|upgrade|season\s*pass|cosmetic|"
    r"offline\s*activation|cd[\s-]?key\s*only"
    r")\b",
    re.I,
)

# Official storefronts (plus Offer.is_official). Keyshops are never MSRP-fallback eligible.
_OFFICIAL_SHOP_NAMES = frozenset(
    {
        "steam",
        "steam us",
        "epic games",
        "epic",
        "gog",
        "microsoft store",
        "xbox",
        "playstation store",
        "nintendo eshop",
        "humble",
        "humble store",
    }
)
_KEYSHOP_SHOP_NAMES = frozenset(
    {
        "g2a",
        "kinguin",
        "instant gaming",
        "gamivo",
        "cdkeys",
        "eneba",
        "fanatical",
        "green man gaming",
    }
)
# Same underlying storefront family — collapse duplicate editorial surfaces.
_STEAM_FAMILY = frozenset({"steam", "steam us"})
_EPIC_FAMILY = frozenset({"epic games", "epic"})
_CONF_RANK = {CONF_HIGH: 3, CONF_MEDIUM: 2, CONF_LOW: 1}

_STARTED = False
_LOCK = threading.Lock()
_SHOPS_TRUST: dict[str, Any] | None = None


@dataclass
class _Event:
    game: Game
    shop_name: str | None
    candidate_type: str
    price_current: float
    price_previous: float | None
    discount_percent: int | None
    score: int
    reason_text: str
    historical_minimum: float | None = None
    historical_period_days: int | None = None
    history_start_at: datetime | None = None
    valid_until: datetime | None = None
    confidence: str = CONF_HIGH
    evidence_source: str | None = None
    offer_updated_at: datetime | None = None
    alternate_offers: list[dict[str, Any]] | None = None


def _fingerprint(
    game_id: int,
    candidate_type: str,
    shop: str | None,
    price: float | None,
) -> str:
    """Stable dedupe key stored in DiscoverCandidate.fingerprint.

    Composition (exact):
      sha256(f\"{game_id}|{candidate_type}|{shop.lower()}|{round(price, 2)}\")[:40]

    Implications:
    - same game + type + shop + price bucket → same fingerprint (idempotent)
    - same game, different store → different fingerprint (intentional)
    - new lower price → different fingerprint (may create new row; cooldown may skip
      same type unless price is strictly lower than the recent same-type row)
    """
    bucket = round(float(price or 0), 2)
    raw = f"{game_id}|{candidate_type}|{(shop or '').lower()}|{bucket}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _discount_score(discount: int) -> int:
    if discount >= 90:
        return SCORE_DISC_90
    if discount >= 80:
        return SCORE_DISC_80
    if discount >= 70:
        return SCORE_DISC_70
    if discount >= 50:
        return SCORE_DISC_50
    return 0


def _popular_bonus(game: Game) -> int:
    """Popularity bonus only above an explicit review threshold (not mere presence)."""
    reviews = game.steam_review_count
    if reviews is None:
        return 0
    try:
        n = int(reviews)
    except (TypeError, ValueError):
        return 0
    if n >= POPULAR_REVIEW_MIN:
        return SCORE_POPULAR
    return 0


def _pct_drop(previous: float, current: float) -> int | None:
    if previous <= 0 or current < 0:
        return None
    if current >= previous:
        return None
    return int(round((previous - current) / previous * 100))


def _is_significant_drop(previous: float, current: float) -> bool:
    if previous <= 0 or current < 0 or current >= previous:
        return False
    abs_drop = previous - current
    rel = (abs_drop / previous) * 100.0
    return abs_drop >= MIN_ABS_DROP_PLN and rel >= MIN_REL_DROP_PCT


def _valid_price(value: float | None) -> bool:
    if value is None:
        return False
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False
    if v != v:  # NaN
        return False
    return v >= 0


def _offer_is_fresh(offer: Offer, *, now: datetime | None = None) -> bool:
    """Reject stale in_stock rows so old zeros cannot become 'news'."""
    now = now or datetime.utcnow()
    updated = offer.updated_at
    if updated is None:
        return False
    age_h = (now - updated).total_seconds() / 3600.0
    return age_h <= MAX_OFFER_AGE_HOURS


def _is_non_full_game(game: Game) -> bool:
    app_type = (game.steam_app_type or "").strip().lower()
    if app_type in _NON_FULL_GAME_TYPES:
        return True
    title = game.title or ""
    if _TITLE_REJECT_RE.search(title):
        return True
    return False


def _list_price_sane(current: float, list_price: float) -> bool:
    if list_price <= current or list_price <= 0:
        return False
    if list_price / max(current, 0.01) > MAX_LIST_PRICE_RATIO:
        return False
    return True


def _shops_trust() -> dict[str, Any]:
    global _SHOPS_TRUST
    if _SHOPS_TRUST is not None:
        return _SHOPS_TRUST
    try:
        from app.core.shops_trust import load_shops_trust

        _SHOPS_TRUST = load_shops_trust()
    except Exception:
        _SHOPS_TRUST = {}
    return _SHOPS_TRUST

def _shop_key(shop_name: str | None) -> str:
    return (shop_name or "").strip().lower()


def _is_official_shop(offer: Offer) -> bool:
    """Prefer Offer.is_official; fall back to shops_trust / known official names."""
    if getattr(offer, "is_official", None) is True:
        return True
    key = _shop_key(offer.shop_name)
    if key in _OFFICIAL_SHOP_NAMES:
        return True
    meta = _shops_trust().get(offer.shop_name or "") or _shops_trust().get(
        (offer.shop_name or "").strip()
    )
    if isinstance(meta, dict) and meta.get("is_official") is True:
        return True
    return False


def _is_keyshop(offer: Offer) -> bool:
    if _is_official_shop(offer):
        return False
    key = _shop_key(offer.shop_name)
    if key in _KEYSHOP_SHOP_NAMES:
        return True
    meta = _shops_trust().get(offer.shop_name or "")
    if isinstance(meta, dict) and meta.get("is_official") is False:
        return True
    return False


def _original_price_trustworthy(offer: Offer, current: float) -> float | None:
    """Return usable same-offer original/list price, or None if untrustworthy.

    Trust rules (documented):
    - Official stores (Steam/Epic/GOG/… via is_official or shops_trust):
      original_price from store APIs is accepted when sane.
    - Keyshops: original_price is rare; accept only when sane AND not an
      obvious foreign MSRP copy (ratio already capped) AND match_confidence
      is null/unknown or >= 0.55 when present.
    - Never accept original <= current, <= 0, NaN, or ratio > MAX_LIST_PRICE_RATIO.
    """
    orig = offer.original_price_pln
    if orig is None or not _valid_price(orig):
        return None
    value = float(orig)
    if not _list_price_sane(current, value):
        return None
    if _is_official_shop(offer):
        return value
    # Keyshop / unknown: require sane original; reject low match confidence.
    conf = getattr(offer, "match_confidence", None)
    if conf is not None:
        try:
            if float(conf) < 0.55:
                return None
        except (TypeError, ValueError):
            return None
    return value


def _confidence_bonus(confidence: str) -> int:
    if confidence == CONF_HIGH:
        return SCORE_CONF_HIGH
    if confidence == CONF_MEDIUM:
        return SCORE_CONF_MEDIUM
    return 0


def _editorial_score(base: int, game: Game, confidence: str) -> int:
    """Score only HIGH/MEDIUM editorial candidates. LOW → 0 (excluded)."""
    if confidence not in EDITORIAL_CONFIDENCE:
        return 0
    return base + _confidence_bonus(confidence) + _popular_bonus(game)


def _prior_history(
    db: Session,
    game_id: int,
    *,
    before: datetime,
) -> tuple[float | None, int, int, datetime | None]:
    """Prior KupujPL snapshots strictly before ``before`` (excludes current event)."""
    row = (
        db.query(
            func.min(PriceSnapshot.price_pln),
            func.count(PriceSnapshot.id),
            func.min(PriceSnapshot.recorded_at),
            func.max(PriceSnapshot.recorded_at),
        )
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.price_pln > 0,
            PriceSnapshot.recorded_at < before,
        )
        .one()
    )
    min_price, count, first_at, last_at = row
    if not count or min_price is None or not first_at or not last_at:
        return None, 0, 0, None
    period_days = max(0, int((last_at - first_at).total_seconds() // 86400))
    return float(min_price), int(count), period_days, first_at


def _history_is_proven(count: int, period_days: int) -> bool:
    return count >= HIST_MIN_SNAPSHOTS and period_days >= HIST_MIN_DAYS


def _same_shop_prior_paid(
    db: Session,
    *,
    game_id: int,
    shop_name: str,
    before: datetime,
) -> tuple[float | None, datetime | None, int]:
    """Last non-zero same-shop snapshot before ``before``, plus paid-snap count.

    Returns (price, recorded_at, paid_snapshot_count). Count is used to reject
    weak single-scrape baselines (permanent F2P / parser one-offs).
    """
    paid_count = (
        db.query(func.count(PriceSnapshot.id))
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.shop_name == shop_name,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.price_pln > FREE_PREV_MIN,
            PriceSnapshot.recorded_at < before,
        )
        .scalar()
        or 0
    )
    row = (
        db.query(PriceSnapshot.price_pln, PriceSnapshot.recorded_at)
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.shop_name == shop_name,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.price_pln > FREE_PREV_MIN,
            PriceSnapshot.recorded_at < before,
        )
        .order_by(PriceSnapshot.recorded_at.desc())
        .first()
    )
    if not row:
        return None, None, int(paid_count)
    return float(row[0]), row[1], int(paid_count)


def _title_templates(
    *,
    game_title: str,
    candidate_type: str,
    price: float | None,
    prev: float | None,
    discount: int | None,
    period_days: int | None,
) -> tuple[str, str, str]:
    """Return (title, lead, article_type) — factual Polish suggestions only."""
    price_s = f"{price:.2f}".replace(".", ",") if price is not None else "?"
    disc = discount or 0
    if candidate_type == TYPE_FREE:
        title = f"{game_title} za darmo. Oferta dostępna przez ograniczony czas"
        lead = (
            f"{game_title} jest obecnie dostępne za 0 zł w porównaniu KupujPL. "
            f"Oferta może być ograniczona czasowo."
        )
        return title, lead, "free_game"
    if candidate_type == TYPE_EXPIRE:
        title = f"Promocja na {game_title} wkrótce się kończy. Cena: {price_s} zł"
        lead = (
            f"Według danych KupujPL promocja na {game_title} zbliża się do końca. "
            f"Aktualna cena to {price_s} zł."
        )
        return title, lead, "deal"
    if candidate_type == TYPE_HIST:
        title = f"{game_title} w najniższej cenie zarejestrowanej przez KupujPL"
        days = period_days or 0
        lead = (
            f"{game_title} kosztuje teraz {price_s} zł — to najniższa cena "
            f"zarejestrowana przez KupujPL w okresie obserwacji ({days} dni). "
            f"Nie jest to gwarantowane historyczne minimum rynku."
        )
        return title, lead, "price_drop"
    if candidate_type == TYPE_BIG:
        # List/original/Steam reference — not "previous observed selling price"
        title = f"{game_title} przecenione o {disc}%. Cena spadła do {price_s} zł"
        lead = (
            f"{game_title} ma zniżkę −{disc}% względem ceny katalogowej / referencyjnej. "
            f"Aktualna cena oferty to {price_s} zł."
        )
        return title, lead, "deal"
    # price_drop — prior observed selling price only
    title = f"Cena {game_title} spadła do {price_s} zł"
    lead = f"Aktualna cena {game_title} w porównaniu KupujPL to {price_s} zł."
    if prev is not None:
        prev_s = f"{prev:.2f}".replace(".", ",")
        lead += f" Wcześniej w tym samym sklepie obserwowaliśmy ok. {prev_s} zł."
    return title, lead, "price_drop"


def _facts_block(
    *,
    game: Game,
    shop: str | None,
    price: float | None,
    prev: float | None,
    discount: int | None,
    reason_text: str,
    historical_minimum: float | None,
    historical_period_days: int | None,
    valid_until: datetime | None,
) -> str:
    """Editorial facts only — no fabricated prose."""
    lines = [f"<p>{reason_text}</p>", "<ul>"]
    if shop and price is not None:
        lines.append(f"<li>Sklep: <strong>{shop}</strong> — <strong>{price:.2f} zł</strong></li>")
    elif price is not None:
        lines.append(f"<li>Cena: <strong>{price:.2f} zł</strong></li>")
    if prev is not None:
        lines.append(f"<li>Poprzednia / referencyjna cena: {prev:.2f} zł</li>")
    if discount is not None:
        lines.append(f"<li>Zniżka: −{discount}%</li>")
    if historical_minimum is not None:
        days = historical_period_days if historical_period_days is not None else "?"
        lines.append(
            f"<li>Poprzednie minimum KupujPL: {historical_minimum:.2f} zł "
            f"(okres obserwacji: {days} dni)</li>"
        )
    if valid_until is not None:
        lines.append(f"<li>Ważne do: {valid_until.isoformat()}Z</li>")
    lines.append("</ul>")
    lines.append(
        f'<p><a href="/games/gra/{game.slug}">Sprawdź aktualne ceny {game.title} w KupujPL Games</a>.</p>'
    )
    return "\n".join(lines)


def _previous_snapshot_price(
    db: Session,
    *,
    game_id: int,
    shop_name: str,
    before: datetime,
    max_age_days: int | None = None,
) -> tuple[float | None, datetime | None]:
    """Most recent same-shop in-stock price strictly before ``before``.

    When ``max_age_days`` is set, reject priors older than that window relative
    to ``before`` (avoids ancient unrelated history as 'current sale' proof).
    """
    row = (
        db.query(PriceSnapshot.price_pln, PriceSnapshot.recorded_at)
        .filter(
            PriceSnapshot.game_id == game_id,
            PriceSnapshot.shop_name == shop_name,
            PriceSnapshot.in_stock.is_(True),
            PriceSnapshot.price_pln > 0,
            PriceSnapshot.recorded_at < before,
        )
        .order_by(PriceSnapshot.recorded_at.desc())
        .first()
    )
    if not row:
        return None, None
    price, recorded_at = float(row[0]), row[1]
    if max_age_days is not None and recorded_at is not None:
        age_days = (before - recorded_at).total_seconds() / 86400.0
        if age_days > max_age_days:
            return None, recorded_at
    return price, recorded_at


def _detect_free_events(db: Session, *, limit: int = 80) -> list[_Event]:
    """Promotional free only — never permanent F2P / stale / cross-shop zeros.

    Acceptance (all required):
    - in_stock True, price in [0, 0.01], fresh updated_at (<= MAX_OFFER_AGE_HOURS)
    - game.is_free is False
    - not DLC/demo/bundle/friend-pass by type/title
    - SAME-shop prior paid evidence:
        * prior snapshot for this shop > FREE_PREV_MIN, OR
        * original_price_pln > FREE_PREV_MIN (sane list price on this offer)
    Rejection examples: permanent Epic F2P (PoE2/Rocket League), stale Steam 0
    with original=0 (Ship It), Friend's Pass, using another shop's paid price as 'previous'.
    """
    events: list[_Event] = []
    now = datetime.utcnow()
    fresh_since = now - timedelta(hours=MAX_OFFER_AGE_HOURS)
    free_offers = (
        db.query(Offer)
        .options(joinedload(Offer.game))
        .filter(
            Offer.in_stock.is_(True),
            Offer.price_pln.isnot(None),
            Offer.price_pln >= 0,
            Offer.price_pln <= 0.01,
            Offer.updated_at.isnot(None),
            Offer.updated_at >= fresh_since,
        )
        .order_by(Offer.updated_at.desc())
        .limit(limit * 4)
        .all()
    )
    seen_games: set[int] = set()
    for offer in free_offers:
        game = offer.game
        if not game or game.id in seen_games:
            continue
        if game.is_free or _is_non_full_game(game):
            continue
        if not _valid_price(offer.price_pln) or not _offer_is_fresh(offer, now=now):
            continue
        before = offer.updated_at or now
        prev, prev_at, paid_snaps = _same_shop_prior_paid(
            db, game_id=game.id, shop_name=offer.shop_name, before=before
        )
        evidence = "snapshot"
        if prev is not None and prev_at is not None:
            age_days = (before - prev_at).total_seconds() / 86400.0
            if age_days > FREE_PRIOR_MAX_AGE_DAYS:
                prev = None  # too old to prove a promo transition
            elif paid_snaps < FREE_MIN_SAME_SHOP_PAID_SNAPS:
                prev = None  # weak single-scrape / permanent-F2P baseline
        if prev is None:
            orig = offer.original_price_pln
            if (
                orig is not None
                and _valid_price(orig)
                and float(orig) > FREE_PREV_MIN
                and _list_price_sane(0.01, float(orig))
            ):
                prev = float(orig)
                evidence = "original_price"
        if prev is None or prev <= 0:
            continue
        seen_games.add(game.id)
        conf = CONF_HIGH
        events.append(
            _Event(
                game=game,
                shop_name=offer.shop_name,
                candidate_type=TYPE_FREE,
                price_current=0.0,
                price_previous=prev,
                discount_percent=100,
                score=_editorial_score(SCORE_FREE, game, conf),
                reason_text=(
                    f"Promocyjne 0 zł w {offer.shop_name} dla {game.title} "
                    f"(wcześniejsza cena w tym samym sklepie / katalogu: {prev:.2f} zł; "
                    f"dowód: {evidence})."
                ),
                confidence=conf,
                evidence_source=evidence,
            )
        )
        if len(events) >= limit:
            break
    return events


def _detect_discount_and_drop_events(
    db: Session, *, limit: int = 200
) -> tuple[list[_Event], int]:
    """STORE_DISCOUNT_EVENT → editorial; MSRP_PRICE_GAP → counted, not persisted.

    big_discount requires same-offer trustworthy original_price OR a fresh
    same-shop prior selling-price drop (≥ MIN_DISCOUNT_PCT).

    Steam/list MSRP alone (keyshop vs Steam) is MSRP_PRICE_GAP — excluded from
    the default editorial queue and not scored as a normal candidate.
    """
    events: list[_Event] = []
    msrp_excluded = 0
    now = datetime.utcnow()
    since = now - timedelta(hours=min(SCAN_OFFER_HOURS, MAX_OFFER_AGE_HOURS))
    offers = (
        db.query(Offer)
        .options(joinedload(Offer.game))
        .filter(
            Offer.in_stock.is_(True),
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
            Offer.updated_at.isnot(None),
            Offer.updated_at >= since,
        )
        .order_by(Offer.updated_at.desc())
        .limit(limit * 4)
        .all()
    )
    game_ids = {o.game_id for o in offers if o.game_id}
    steam_map: dict[int, float] = {}
    if game_ids:
        steam_rows = (
            db.query(Offer.game_id, func.min(Offer.price_pln))
            .filter(
                Offer.game_id.in_(list(game_ids)),
                Offer.in_stock.is_(True),
                Offer.shop_name == "Steam",
                Offer.price_pln > 0,
            )
            .group_by(Offer.game_id)
            .all()
        )
        steam_map = {int(gid): float(price) for gid, price in steam_rows}

    for offer in offers:
        game = offer.game
        if not game or game.is_free or _is_non_full_game(game):
            continue
        if not _valid_price(offer.price_pln) or not _offer_is_fresh(offer, now=now):
            continue
        current = float(offer.price_pln)
        before = offer.updated_at or now
        official = _is_official_shop(offer)

        # --- same-shop prior selling price (recent window only) ---
        prior, prior_at = _previous_snapshot_price(
            db,
            game_id=game.id,
            shop_name=offer.shop_name,
            before=before,
            max_age_days=PRIOR_PROMO_MAX_AGE_DAYS,
        )
        if prior is not None and prior / max(current, 0.01) > MAX_SAME_SHOP_DROP_RATIO:
            # Extreme same-shop cliff (wrong SKU / mismatched product) — not editorial.
            prior = None
        prior_disc = _pct_drop(prior, current) if prior is not None else None
        prior_significant = prior is not None and _is_significant_drop(prior, current)

        # --- same-offer original_price (store promo list) ---
        orig = _original_price_trustworthy(offer, current)
        orig_disc = _pct_drop(orig, current) if orig is not None else None

        store_event = False

        # Prefer same-store original for official stores; still allow keyshop original.
        if orig is not None and orig_disc is not None and orig_disc >= MIN_DISCOUNT_PCT:
            base = _discount_score(orig_disc)
            if base:
                conf = CONF_HIGH if official else CONF_MEDIUM
                events.append(
                    _Event(
                        game=game,
                        shop_name=offer.shop_name,
                        candidate_type=TYPE_BIG,
                        price_current=current,
                        price_previous=orig,
                        discount_percent=orig_disc,
                        score=_editorial_score(base, game, conf),
                        reason_text=(
                            f"{game.title}: zniżka −{orig_disc}% względem ceny katalogowej "
                            f"tej oferty (original_price {orig:.2f} zł → {current:.2f} zł "
                            f"w {offer.shop_name})."
                        ),
                        confidence=conf,
                        evidence_source="original_price",
                        offer_updated_at=offer.updated_at,
                    )
                )
                store_event = True

        # Same-shop prior drop at big_discount threshold (actual store promotion).
        if (
            not store_event
            and prior is not None
            and prior_disc is not None
            and prior_disc >= MIN_DISCOUNT_PCT
        ):
            base = _discount_score(prior_disc)
            if base:
                conf = CONF_HIGH
                events.append(
                    _Event(
                        game=game,
                        shop_name=offer.shop_name,
                        candidate_type=TYPE_BIG,
                        price_current=current,
                        price_previous=prior,
                        discount_percent=prior_disc,
                        score=_editorial_score(base, game, conf),
                        reason_text=(
                            f"{game.title}: zniżka −{prior_disc}% w {offer.shop_name} "
                            f"(obserwowana cena w tym sklepie {prior:.2f} zł → {current:.2f} zł)."
                        ),
                        confidence=conf,
                        evidence_source="same_shop_prior",
                        offer_updated_at=offer.updated_at,
                    )
                )
                store_event = True

        # Smaller but significant same-shop drop → price_drop only.
        if not store_event and prior_significant:
            disc = prior_disc
            conf = CONF_HIGH
            events.append(
                _Event(
                    game=game,
                    shop_name=offer.shop_name,
                    candidate_type=TYPE_DROP,
                    price_current=current,
                    price_previous=prior,
                    discount_percent=disc,
                    score=_editorial_score(
                        SCORE_PRICE_DROP + (_discount_score(disc or 0) // 5),
                        game,
                        conf,
                    ),
                    reason_text=(
                        f"Cena {game.title} w {offer.shop_name} spadła "
                        f"z obserwowanych {prior:.2f} zł do {current:.2f} zł."
                    ),
                    confidence=conf,
                    evidence_source="same_shop_prior",
                    offer_updated_at=offer.updated_at,
                )
            )
            store_event = True

        # --- MSRP_PRICE_GAP: Steam/list only — never editorial ---
        if not store_event:
            steam = steam_map.get(game.id)
            shop_l = _shop_key(offer.shop_name)
            if (
                steam is not None
                and shop_l not in ("steam", "steam us")
                and _list_price_sane(current, steam)
            ):
                gap = _pct_drop(steam, current)
                if gap is not None and gap >= MIN_DISCOUNT_PCT:
                    msrp_excluded += 1
                    # Intentionally not appended: LOW / MSRP_PRICE_GAP is not an
                    # editorial Discover candidate and receives no normal score.

        if len(events) >= limit * 2:
            break
    return events, msrp_excluded


def _hist_low_offer_eligible(offer: Offer) -> bool:
    """Historical lows are PLN/local official storefronts only — not keyshops or Steam US."""
    if not _is_official_shop(offer):
        return False
    # Steam US mirrors often undercut PLN history via FX; editorial queue stays PL-first.
    if _shop_key(offer.shop_name) == "steam us":
        return False
    return True


def _detect_historical_low_events(db: Session, *, limit: int = 40) -> list[_Event]:
    """Strict prior-minimum: current must be < previous observed min (not <=)."""
    events: list[_Event] = []
    now = datetime.utcnow()
    fresh_since = now - timedelta(hours=MAX_OFFER_AGE_HOURS)
    # Candidate games: any fresh in-stock offer (eligibility checked on official row).
    game_ids = [
        gid
        for (gid,) in (
            db.query(Offer.game_id)
            .filter(
                Offer.in_stock.is_(True),
                Offer.price_pln > 0,
                Offer.updated_at.isnot(None),
                Offer.updated_at >= fresh_since,
            )
            .distinct()
            .limit(limit * 8)
            .all()
        )
    ]
    if not game_ids:
        return events
    games = (
        db.query(Game)
        .filter(Game.id.in_(game_ids), Game.is_free.is_(False))
        .order_by(Game.steam_review_count.desc())
        .all()
    )
    for game in games:
        if _is_non_full_game(game):
            continue
        fresh_offers = (
            db.query(Offer)
            .filter(
                Offer.game_id == game.id,
                Offer.in_stock.is_(True),
                Offer.price_pln > 0,
                Offer.updated_at.isnot(None),
                Offer.updated_at >= fresh_since,
            )
            .order_by(Offer.price_pln.asc(), Offer.updated_at.desc())
            .all()
        )
        offer = next((o for o in fresh_offers if _hist_low_offer_eligible(o)), None)
        if not offer or not _offer_is_fresh(offer, now=now):
            continue
        current = float(offer.price_pln)
        before = offer.updated_at or now
        prior_min, count, period_days, history_start = _prior_history(
            db, game.id, before=before
        )
        if not _history_is_proven(count, period_days) or prior_min is None:
            continue
        # Strictly lower than prior observed minimum (exclude current from baseline)
        if current >= prior_min:
            continue
        events.append(
            _Event(
                game=game,
                shop_name=offer.shop_name,
                candidate_type=TYPE_HIST,
                price_current=current,
                price_previous=prior_min,
                discount_percent=_pct_drop(prior_min, current),
                score=_editorial_score(SCORE_HIST_LOW, game, CONF_HIGH),
                reason_text=(
                    f"Najniższa cena zarejestrowana przez KupujPL dla {game.title}: "
                    f"{current:.2f} zł (wcześniejsze minimum obserwacji: {prior_min:.2f} zł; "
                    f"okres {period_days} dni, {count} wcześniejszych pomiarów)."
                ),
                historical_minimum=prior_min,
                historical_period_days=period_days,
                history_start_at=history_start,
                confidence=CONF_HIGH,
                evidence_source="prior_snapshots",
            )
        )
        if len(events) >= limit:
            break
    return events


def _detect_expiring_events(db: Session, *, limit: int = 30) -> list[_Event]:
    """Only when giveaway payload provides ends_at — never invent expiry."""
    events: list[_Event] = []
    try:
        from app.parsers.free_giveaways import get_free_giveaways

        payload = get_free_giveaways(db)
    except Exception as exc:
        logger.debug("giveaways unavailable for expiry scan: %s", exc)
        return events
    now = datetime.utcnow()
    horizon = now + timedelta(hours=48)
    for item in (payload.get("current") or []):
        ends_raw = item.get("ends_at")
        if not ends_raw:
            continue
        try:
            ends = datetime.fromisoformat(str(ends_raw).replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            continue
        if ends < now or ends > horizon:
            continue
        hours_left = (ends - now).total_seconds() / 3600.0
        game = None
        slug = item.get("slug")
        appid = item.get("steam_appid")
        if slug:
            game = db.query(Game).filter(Game.slug == slug).first()
        if not game and appid:
            try:
                game = db.query(Game).filter(Game.steam_appid == int(appid)).first()
            except (TypeError, ValueError):
                game = None
        if not game or game.is_free or _is_non_full_game(game):
            continue
        score = SCORE_EXPIRE_24 if hours_left <= 24 else SCORE_EXPIRE_48
        conf = CONF_HIGH
        events.append(
            _Event(
                game=game,
                shop_name=item.get("shop"),
                candidate_type=TYPE_EXPIRE,
                price_current=0.0,
                price_previous=item.get("original_price_pln"),
                discount_percent=100 if item.get("original_price_pln") else None,
                score=_editorial_score(score + SCORE_FREE // 5, game, conf),
                reason_text=(
                    f"Promocja na {game.title} kończy się w ciągu "
                    f"{'24h' if hours_left <= 24 else '48h'} "
                    f"(do {ends.isoformat()}Z)."
                ),
                valid_until=ends,
                confidence=conf,
                evidence_source="giveaway_ends_at",
            )
        )
        if len(events) >= limit:
            break
    return events


def _payload_for(event: _Event) -> str:
    data: dict[str, Any] = {
        "game_slug": event.game.slug,
        "game_title": event.game.title,
        "reason_text": event.reason_text,
        "candidate_type": event.candidate_type,
        # Internal editorial confidence — never exposed in public SEO templates.
        "confidence": event.confidence,
        "evidence_source": event.evidence_source,
        "primary_store": event.shop_name,
        "best_offer": {
            "shop_name": event.shop_name,
            "price_current": event.price_current,
            "price_previous": event.price_previous,
            "discount_percent": event.discount_percent,
        },
    }
    if event.alternate_offers:
        data["alternate_offers"] = event.alternate_offers
    if event.history_start_at is not None:
        data["history_start_at"] = event.history_start_at.isoformat()
    return json.dumps(data, ensure_ascii=False)


def _store_family(shop_name: str | None) -> str:
    key = _shop_key(shop_name)
    if key in _STEAM_FAMILY:
        return "steam_family"
    if key in _EPIC_FAMILY:
        return "epic_family"
    return key or "unknown"


def _is_local_pln_store(shop_name: str | None) -> bool:
    """Prefer EU/PLN storefronts over regional mirrors (Steam over Steam US)."""
    key = _shop_key(shop_name)
    if key == "steam us":
        return False
    if key in _STEAM_FAMILY or key in _EPIC_FAMILY or key in {"gog", "humble", "humble store"}:
        return True
    return True


def _primary_event_key(event: _Event) -> tuple:
    """Sort key: higher is better primary candidate."""
    conf = _CONF_RANK.get(event.confidence, 0)
    local = 1 if _is_local_pln_store(event.shop_name) else 0
    # Prefer Steam (PL) over Steam US within family
    steam_pl = 1 if _shop_key(event.shop_name) == "steam" else 0
    price = -(event.price_current or 0)  # lower price better → negate for max
    fresh = (event.offer_updated_at or datetime.min).timestamp()
    evidence_rank = 2 if event.evidence_source == "original_price" else 1
    return (conf, local, steam_pl, evidence_rank, price, fresh, event.score)


def _equivalent_promo(a: _Event, b: _Event) -> bool:
    """True when two events are the same underlying promotion surface."""
    if a.game.id != b.game.id or a.candidate_type != b.candidate_type:
        return False
    if _store_family(a.shop_name) != _store_family(b.shop_name):
        return False
    # Different store families (e.g. Steam vs GOG) never merge.
    fam = _store_family(a.shop_name)
    if fam not in ("steam_family", "epic_family"):
        return False
    # Same evidence class preferred; allow original_price with original_price.
    if a.evidence_source and b.evidence_source and a.evidence_source != b.evidence_source:
        if {a.evidence_source, b.evidence_source} != {"original_price", "same_shop_prior"}:
            return False
    da = a.discount_percent
    db_ = b.discount_percent
    if da is not None and db_ is not None and abs(int(da) - int(db_)) <= 5:
        return True
    # Relative price within ~25% when discounts missing/differ (FX / regional list).
    if a.price_current > 0 and b.price_current > 0:
        ratio = max(a.price_current, b.price_current) / min(a.price_current, b.price_current)
        if ratio <= 1.35 and (da is None or db_ is None or abs(int(da or 0) - int(db_ or 0)) <= 15):
            return True
    return False


def _collapse_editorial_duplicates(events: list[_Event]) -> tuple[list[_Event], int]:
    """Collapse Steam/Steam US (and Epic mirrors) of the same promo into one event."""
    if not events:
        return [], 0
    # Process highest-score first so winners keep score surface.
    ordered = sorted(events, key=lambda e: e.score, reverse=True)
    groups: list[list[_Event]] = []
    for event in ordered:
        placed = False
        for group in groups:
            if _equivalent_promo(group[0], event):
                group.append(event)
                placed = True
                break
        if not placed:
            groups.append([event])

    collapsed: list[_Event] = []
    removed = 0
    for group in groups:
        if len(group) == 1:
            collapsed.append(group[0])
            continue
        primary = max(group, key=_primary_event_key)
        alts: list[dict[str, Any]] = []
        for other in group:
            if other is primary:
                continue
            removed += 1
            alts.append(
                {
                    "shop_name": other.shop_name,
                    "price_current": other.price_current,
                    "price_previous": other.price_previous,
                    "discount_percent": other.discount_percent,
                    "evidence_source": other.evidence_source,
                    "confidence": other.confidence,
                }
            )
        primary.alternate_offers = alts
        # Canonical fingerprint shop for Steam family → "Steam"
        if _store_family(primary.shop_name) == "steam_family":
            if _shop_key(primary.shop_name) != "steam":
                # Prefer keeping primary shop_name as chosen; fingerprint uses it.
                pass
        collapsed.append(primary)
    return collapsed, removed


def _upsert_event(
    db: Session,
    event: _Event,
    *,
    cooldown_since: datetime,
    dry_run: bool,
    stats: dict[str, Any],
) -> None:
    # LOW / MSRP-only never enters the editorial candidate table.
    if event.confidence not in EDITORIAL_CONFIDENCE or event.score <= 0:
        stats["msrp_excluded"] = int(stats.get("msrp_excluded") or 0) + 1
        stats["skipped"] += 1
        return
    fp = _fingerprint(
        event.game.id,
        event.candidate_type,
        event.shop_name,
        event.price_current,
    )
    by_type = stats.setdefault("by_type", {})
    existing = db.query(DiscoverCandidate).filter(DiscoverCandidate.fingerprint == fp).first()
    if existing:
        if existing.status == "ignored":
            stats["skipped"] += 1
            return
        if existing.detected_at and existing.detected_at > cooldown_since:
            if existing.price_current is not None and event.price_current < float(existing.price_current) - 0.01:
                pass
            else:
                stats["skipped"] += 1
                stats["duplicates"] += 1
                return
        if not dry_run:
            existing.score = max(int(existing.score or 0), event.score)
            existing.price_current = event.price_current
            existing.price_previous = event.price_previous
            existing.discount_percent = event.discount_percent
            existing.historical_minimum = event.historical_minimum
            existing.historical_period_days = event.historical_period_days
            existing.valid_until = event.valid_until
            existing.reason = event.candidate_type
            existing.updated_at = datetime.utcnow()
            existing.payload_json = _payload_for(event)
        stats["updated"] += 1
        by_type[event.candidate_type] = by_type.get(event.candidate_type, 0) + 1
        return

    recent = (
        db.query(DiscoverCandidate)
        .filter(
            DiscoverCandidate.game_id == event.game.id,
            DiscoverCandidate.reason == event.candidate_type,
            DiscoverCandidate.detected_at >= cooldown_since,
        )
        .order_by(DiscoverCandidate.detected_at.desc())
        .first()
    )
    if recent:
        recent_price = recent.price_current
        if recent_price is None or event.price_current >= float(recent_price) - 0.01:
            stats["skipped"] += 1
            stats["duplicates"] += 1
            return

    if dry_run:
        stats["created"] += 1
        by_type[event.candidate_type] = by_type.get(event.candidate_type, 0) + 1
        return

    db.add(
        DiscoverCandidate(
            fingerprint=fp,
            game_id=event.game.id,
            reason=event.candidate_type,
            score=event.score,
            shop_name=event.shop_name,
            price_current=event.price_current,
            price_previous=event.price_previous,
            discount_percent=event.discount_percent,
            historical_minimum=event.historical_minimum,
            historical_period_days=event.historical_period_days,
            valid_until=event.valid_until,
            status="open",
            payload_json=_payload_for(event),
        )
    )
    stats["created"] += 1
    by_type[event.candidate_type] = by_type.get(event.candidate_type, 0) + 1


def scan_deal_candidates(
    db: Session,
    *,
    limit: int = 80,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Detect candidates from offers/snapshots/giveaways. Never publishes articles."""
    t0 = time.perf_counter()
    stats: dict[str, Any] = {
        "created": 0,
        "updated": 0,
        "skipped": 0,
        "duplicates": 0,
        "offers_scanned": 0,
        "events_considered": 0,
        "msrp_excluded": 0,
        "editorial_duplicates_collapsed": 0,
        "by_type": {},
        "by_confidence": {},
        "runtime_sec": 0.0,
        "dry_run": dry_run,
        "max_offer_age_hours": MAX_OFFER_AGE_HOURS,
        "prior_promo_max_age_days": PRIOR_PROMO_MAX_AGE_DAYS,
        "scheduler_enabled_flag": SCHEDULER_ENABLED,
    }
    cooldown_since = datetime.utcnow() - timedelta(hours=COOLDOWN_HOURS)
    since = datetime.utcnow() - timedelta(hours=SCAN_OFFER_HOURS)
    stats["offers_scanned"] = (
        db.query(func.count(Offer.id))
        .filter(Offer.in_stock.is_(True), Offer.updated_at >= since)
        .scalar()
        or 0
    )

    events: list[_Event] = []
    events.extend(_detect_free_events(db, limit=limit))
    disc_events, msrp_excluded = _detect_discount_and_drop_events(db, limit=limit)
    events.extend(disc_events)
    stats["msrp_excluded"] = msrp_excluded
    events.extend(_detect_historical_low_events(db, limit=min(40, limit)))
    events.extend(_detect_expiring_events(db, limit=min(30, limit)))
    # Editorial queue = HIGH + MEDIUM only
    editorial = [e for e in events if e.confidence in EDITORIAL_CONFIDENCE and e.score > 0]
    editorial, collapsed_n = _collapse_editorial_duplicates(editorial)
    stats["editorial_duplicates_collapsed"] = collapsed_n
    stats["events_considered"] = len(editorial)
    by_conf = stats.setdefault("by_confidence", {})
    for e in editorial:
        by_conf[e.confidence] = by_conf.get(e.confidence, 0) + 1

    editorial.sort(key=lambda e: e.score, reverse=True)
    capped = editorial[: max(limit * 3, 50)]
    for event in capped:
        _upsert_event(db, event, cooldown_since=cooldown_since, dry_run=dry_run, stats=stats)

    if not dry_run:
        db.commit()
    else:
        db.rollback()

    stats["runtime_sec"] = round(time.perf_counter() - t0, 3)
    if dry_run:
        samples = []
        for e in sorted(editorial, key=lambda x: x.score, reverse=True)[:20]:
            samples.append(
                {
                    "game": e.game.title,
                    "store": e.shop_name,
                    "current": e.price_current,
                    "previous": e.price_previous,
                    "discount": e.discount_percent,
                    "historical_previous_minimum": e.historical_minimum,
                    "history_days": e.historical_period_days,
                    "type": e.candidate_type,
                    "score": e.score,
                    "confidence": e.confidence,
                    "evidence_source": e.evidence_source,
                    "alternate_offers": e.alternate_offers or [],
                    "reason": e.reason_text,
                }
            )
        stats["samples"] = samples
        stats["editorial_total"] = len(editorial)
    logger.info(
        "deal candidate scan: created=%s updated=%s skipped=%s offers=%s by_type=%s "
        "msrp_excluded=%s runtime=%ss dry_run=%s",
        stats["created"],
        stats["updated"],
        stats["skipped"],
        stats["offers_scanned"],
        stats["by_type"],
        stats["msrp_excluded"],
        stats["runtime_sec"],
        dry_run,
    )
    return stats


def _confidence_from_row(row: DiscoverCandidate) -> str:
    if row.payload_json:
        try:
            data = json.loads(row.payload_json)
            conf = (data.get("confidence") or "").upper()
            if conf in (CONF_HIGH, CONF_MEDIUM, CONF_LOW):
                return conf
        except json.JSONDecodeError:
            pass
    # Legacy rows without confidence → treat as MEDIUM (same-store era unknown).
    return CONF_MEDIUM


def list_candidates(
    db: Session,
    *,
    status: str | None = "open",
    reason: str | None = None,
    limit: int = 100,
    include_low_confidence: bool = False,
) -> list[DiscoverCandidate]:
    q = db.query(DiscoverCandidate).order_by(
        DiscoverCandidate.score.desc(),
        DiscoverCandidate.detected_at.desc(),
    )
    # Status aliases from Phase-2 UI
    if status in ("new", "open", ""):
        status = "open" if status != "" else None
    elif status == "converted":
        status = "drafted"
    if status:
        q = q.filter(DiscoverCandidate.status == status)
    if reason:
        if reason in ("70+", "price_drop_70"):
            q = q.filter(DiscoverCandidate.discount_percent >= 70)
        elif reason in ("50+", "price_drop_50", "big_discount"):
            q = q.filter(DiscoverCandidate.discount_percent >= 50)
        elif reason in ("historical_low", "new_low"):
            q = q.filter(DiscoverCandidate.reason.in_([TYPE_HIST, "new_low"]))
        elif reason in ("expiring_deal", "expiring_soon"):
            q = q.filter(DiscoverCandidate.reason.in_([TYPE_EXPIRE, "expiring_soon"]))
        elif reason == "free_game":
            q = q.filter(DiscoverCandidate.reason == TYPE_FREE)
        else:
            q = q.filter(DiscoverCandidate.reason == reason)
    # Over-fetch then filter LOW out of the default panel queue.
    rows = q.limit(limit * 3 if not include_low_confidence else limit).all()
    if include_low_confidence:
        return rows[:limit]
    filtered = [r for r in rows if _confidence_from_row(r) in EDITORIAL_CONFIDENCE]
    return filtered[:limit]


def reason_text_for(row: DiscoverCandidate) -> str:
    if row.payload_json:
        try:
            data = json.loads(row.payload_json)
            txt = (data.get("reason_text") or "").strip()
            if txt:
                return txt
        except json.JSONDecodeError:
            pass
    return row.reason or ""


def ignore_candidate(db: Session, cand_id: int) -> DiscoverCandidate | None:
    row = db.query(DiscoverCandidate).filter(DiscoverCandidate.id == cand_id).first()
    if not row:
        return None
    row.status = "ignored"
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


def draft_from_candidate(db: Session, cand_id: int) -> Article | None:
    """Create Article(status=draft) only — never published.

    Duplicate create-draft on an already-converted candidate returns the linked
    draft article (idempotent) and never publishes.
    """
    row = db.query(DiscoverCandidate).filter(DiscoverCandidate.id == cand_id).first()
    if not row or row.status == "ignored":
        return None
    if row.status == "drafted" and row.article_id:
        existing = db.query(Article).filter(Article.id == row.article_id).first()
        if existing is not None:
            # Idempotent: never create a second article; never publish here.
            return existing
    game = db.query(Game).filter(Game.id == row.game_id).first()
    if not game:
        return None
    ctype = row.reason
    # Map legacy reason codes
    if ctype in ("price_drop_50", "price_drop_70", "popular_drop"):
        ctype = TYPE_BIG if (row.discount_percent or 0) >= 50 else TYPE_DROP
    elif ctype == "new_low":
        ctype = TYPE_HIST
    elif ctype == "expiring_soon":
        ctype = TYPE_EXPIRE

    title, lead, atype = _title_templates(
        game_title=game.title,
        candidate_type=ctype,
        price=row.price_current,
        prev=row.price_previous,
        discount=row.discount_percent,
        period_days=row.historical_period_days,
    )
    content = _facts_block(
        game=game,
        shop=row.shop_name,
        price=row.price_current,
        prev=row.price_previous,
        discount=row.discount_percent,
        reason_text=reason_text_for(row) or lead,
        historical_minimum=row.historical_minimum,
        historical_period_days=row.historical_period_days,
        valid_until=row.valid_until,
    )
    art = create_draft_from_candidate(
        db,
        game=game,
        reason=ctype,
        shop_name=row.shop_name,
        price_current=row.price_current,
        price_previous=row.price_previous,
        discount_percent=row.discount_percent,
        valid_until=row.valid_until,
        title=title,
        lead=lead,
        content=content,
        article_type=atype,
    )
    assert art.status == "draft"
    assert art.date_published is None
    row.status = "drafted"  # converted
    row.article_id = art.id
    row.updated_at = datetime.utcnow()
    db.commit()
    return art


def start_deal_candidate_scheduler() -> None:
    """Hourly background scan — never publishes articles."""
    global _STARTED
    if not SCHEDULER_ENABLED:
        logger.info("Deal candidate scheduler disabled")
        return
    with _LOCK:
        if _STARTED:
            return
        _STARTED = True

    def _loop() -> None:
        # Stagger startup
        time.sleep(90)
        while True:
            try:
                from app.core.database import SessionLocal

                db = SessionLocal()
                try:
                    scan_deal_candidates(db, limit=80, dry_run=False)
                finally:
                    db.close()
            except Exception as exc:
                logger.warning("Deal candidate scheduler cycle failed: %s", exc)
            time.sleep(max(SCHEDULER_INTERVAL_SEC, 600))

    threading.Thread(target=_loop, daemon=True, name="deal-candidates").start()
    logger.info(
        "Deal candidate scheduler started (every %ss)",
        SCHEDULER_INTERVAL_SEC,
    )
