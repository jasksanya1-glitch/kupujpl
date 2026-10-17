"""Central product matching verdicts (product identity only — not price freshness)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from app.core.offer_freshness import evaluate_offer_freshness
from app.core.offer_quality import (
    BEST_PRICE_MIN_CONFIDENCE,
    is_expensive_vs_steam_reference,
    is_keyshop_too_cheap_vs_steam,
    is_peer_price_outlier,
    offer_edition_verified,
    offer_eligible_for_best_price,
    offer_is_suspicious_outlier,
)
from app.core.url_validation import validate_offer_url
from app.models.models import Game, Offer
from app.parsers.keyshop_common import classify_keyshop_product, product_title_from_url

_STEAM_SHOPS = frozenset({"Steam", "Steam US"})
_CONSOLE_OFFICIAL = frozenset({"PlayStation Store", "Xbox Store"})


class MatchStatus(str, Enum):
    VERIFIED_MATCH = "verified_match"
    PENDING_VERIFICATION = "pending_verification"
    VERIFIED_MISMATCH = "verified_mismatch"
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass(frozen=True)
class ProductMatchVerdict:
    status: MatchStatus
    score: float | None
    reason: str | None = None
    url_ok: bool = True
    edition_ok: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "score": self.score,
            "reason": self.reason,
            "url_ok": self.url_ok,
            "edition_ok": self.edition_ok,
        }


@dataclass(frozen=True)
class OfferFreshnessSnapshot:
    status: str
    is_confirmed_fresh: bool
    age_hours: float | None


def evaluate_offer_freshness_snapshot(
    offer: Offer,
    *,
    now: datetime | None = None,
) -> OfferFreshnessSnapshot:
    fr = evaluate_offer_freshness(offer.updated_at, shop_name=offer.shop_name, now=now)
    return OfferFreshnessSnapshot(
        status=fr.status,
        is_confirmed_fresh=fr.is_confirmed_fresh,
        age_hours=fr.age_hours,
    )


def evaluate_product_match(
    offer: Offer,
    game: Game | None,
    *,
    steam_price_pln: float | None = None,
    peer_prices: list[float] | None = None,
    now: datetime | None = None,
) -> ProductMatchVerdict:
    """Whether this row is the same product/edition — independent of freshness."""
    del now  # freshness is separate; kept for API compatibility
    game_title = game.title if game else None
    shop = offer.shop_name or ""
    url = offer.affiliate_url or ""
    price = offer.price_pln

    url_check = validate_offer_url(url, shop)
    if not url_check.ok:
        return ProductMatchVerdict(
            MatchStatus.VERIFIED_MISMATCH,
            score=None,
            reason=f"url:{url_check.result}",
            url_ok=False,
            edition_ok=False,
        )

    if not offer_edition_verified(offer, game_title=game_title):
        return ProductMatchVerdict(
            MatchStatus.VERIFIED_MISMATCH,
            score=None,
            reason="edition_or_sku_mismatch",
            edition_ok=False,
        )

    if not offer.in_stock or price is None or price < 0:
        return ProductMatchVerdict(
            MatchStatus.INSUFFICIENT_DATA,
            score=None,
            reason="not_in_stock",
        )

    if price > 0 and is_expensive_vs_steam_reference(
        float(price), steam_price_pln=steam_price_pln, shop_name=shop
    ):
        return ProductMatchVerdict(
            MatchStatus.VERIFIED_MISMATCH,
            score=None,
            reason="expensive_vs_steam",
        )

    if (
        price > 0
        and shop not in _STEAM_SHOPS
        and shop not in _CONSOLE_OFFICIAL
        and not offer.is_official
    ):
        if is_peer_price_outlier(
            float(price), peer_prices, steam_price_pln=steam_price_pln
        ):
            return ProductMatchVerdict(
                MatchStatus.VERIFIED_MISMATCH,
                score=None,
                reason="peer_price_outlier",
            )
        if is_keyshop_too_cheap_vs_steam(
            float(price),
            steam_price_pln=steam_price_pln,
            shop_name=shop,
            is_official=bool(offer.is_official),
        ):
            return ProductMatchVerdict(
                MatchStatus.VERIFIED_MISMATCH,
                score=None,
                reason="too_cheap_vs_steam",
            )

    if shop in _STEAM_SHOPS or shop in _CONSOLE_OFFICIAL:
        return ProductMatchVerdict(MatchStatus.VERIFIED_MATCH, score=1.0)

    if offer.is_official:
        candidate = product_title_from_url(url)
        if candidate and game_title:
            verdict = classify_keyshop_product(game_title, candidate, url, min_score=0.35)
            if not verdict.get("valid"):
                return ProductMatchVerdict(
                    MatchStatus.VERIFIED_MISMATCH,
                    score=float(verdict.get("score") or 0),
                    reason=str(verdict.get("reason") or "title_mismatch"),
                    edition_ok=False,
                )
        return ProductMatchVerdict(MatchStatus.VERIFIED_MATCH, score=1.0)

    conf = offer.match_confidence
    if conf is None:
        return ProductMatchVerdict(
            MatchStatus.INSUFFICIENT_DATA,
            score=None,
            reason="missing_match_confidence",
        )

    score = float(conf)
    if score < BEST_PRICE_MIN_CONFIDENCE:
        return ProductMatchVerdict(
            MatchStatus.VERIFIED_MISMATCH,
            score=score,
            reason="low_match_confidence",
        )

    if game_title:
        candidate = product_title_from_url(url)
        if candidate:
            verdict = classify_keyshop_product(
                game_title, candidate, url, min_score=BEST_PRICE_MIN_CONFIDENCE
            )
            if not verdict.get("valid"):
                return ProductMatchVerdict(
                    MatchStatus.VERIFIED_MISMATCH,
                    score=float(verdict.get("score") or score),
                    reason=str(verdict.get("reason") or "title_mismatch"),
                )

    return ProductMatchVerdict(MatchStatus.VERIFIED_MATCH, score=score)


def offer_is_confirmed_for_display(
    offer: Offer,
    game: Game | None,
    *,
    steam_price_pln: float | None = None,
    peer_prices: list[float] | None = None,
    now: datetime | None = None,
) -> bool:
    """verified_match + strict fresh + quality gates (hero / KUP TERAZ / catalog best)."""
    match = evaluate_product_match(
        offer, game, steam_price_pln=steam_price_pln, peer_prices=peer_prices, now=now
    )
    if match.status != MatchStatus.VERIFIED_MATCH:
        return False
    fresh = evaluate_offer_freshness_snapshot(offer, now=now)
    if not fresh.is_confirmed_fresh:
        return False
    title = game.title if game else None
    is_free = bool(getattr(game, "is_free", False)) if game else False
    if not offer_eligible_for_best_price(
        offer,
        steam_price_pln=steam_price_pln,
        peer_prices=peer_prices,
        game_title=title,
        now=now,
        require_fresh=True,
        allow_zero_price=is_free,
    ):
        return False
    if offer_is_suspicious_outlier(
        offer,
        steam_price_pln=steam_price_pln,
        peer_prices=peer_prices,
        game_title=title,
    ):
        return False
    return True


def offer_passes_integrity_gate(
    offer: Offer,
    game: Game | None,
    *,
    steam_price_pln: float | None = None,
    peer_prices: list[float] | None = None,
    now: datetime | None = None,
) -> bool:
    """Alias: confirmed offer for min-price surfaces."""
    return offer_is_confirmed_for_display(
        offer,
        game,
        steam_price_pln=steam_price_pln,
        peer_prices=peer_prices,
        now=now,
    )
