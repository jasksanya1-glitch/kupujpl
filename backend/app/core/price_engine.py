"""Unified verified price evaluation for catalog, game page, deals, and API."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.f2p_storefronts import prefer_epic_over_steam_for_free
from app.core.game_offer_selection import (
    display_shops_for_game,
    normalize_shopping_region,
    offer_visible_for_shopping_region,
    steam_shop_for_region,
)
from app.core.offer_freshness import (
    confirmed_unavailable_pl,
    evaluate_offer_freshness,
    format_last_checked_pl,
    freshness_warning_pl,
)
from app.core.offer_quality import offer_edition_verified, offer_eligible_for_best_price
from app.core.product_matching import (
    MatchStatus,
    evaluate_offer_freshness_snapshot,
    evaluate_product_match,
    offer_is_confirmed_for_display,
)
from app.models.models import Game, Offer

ExclusionReason = Literal[
    "out_of_stock",
    "stale",
    "low_confidence",
    "edition_mismatch",
    "peer_outlier",
    "url_invalid",
    "shop_hidden",
    "zero_price_noise",
    "insufficient_data",
    "not_eligible",
    "price_anomaly",
    "match_mismatch",
]

_OFFICIAL_TRUST_SHOPS = frozenset({"Steam", "Steam US", "GOG", "Epic Games", "Fanatical"})
_RECOMMENDED_OFFICIAL_TOLERANCE = 0.08


@dataclass
class PriceEngineOfferRow:
    offer: Offer
    match_status: MatchStatus
    freshness_status: str
    bucket: Literal["confirmed", "stale", "excluded"]
    exclusion_reason: ExclusionReason | None = None


@dataclass
class PriceEngineResult:
    game_id: int
    region: str
    snapshot_at: datetime
    currency: str = "PLN"
    best_confirmed_offer: Offer | None = None
    best_confirmed_price: float | None = None
    best_verified_offer: Offer | None = None
    best_verified_price: float | None = None
    recommended_offer: Offer | None = None
    recommended_reason: str | None = None
    last_known_offer: Offer | None = None
    last_known_price: float | None = None
    confirmed_offers: list[Offer] = field(default_factory=list)
    stale_offers: list[Offer] = field(default_factory=list)
    excluded: list[Offer] = field(default_factory=list)
    exclusion_reasons: dict[int, ExclusionReason] = field(default_factory=dict)
    rows: list[PriceEngineOfferRow] = field(default_factory=list)
    last_checked_label: str | None = None
    confirmed_unavailable_message: str | None = None

    @property
    def has_confirmed(self) -> bool:
        return self.best_confirmed_offer is not None

    @property
    def has_verified(self) -> bool:
        """Backward compat: confirmed snapshot for catalog/API."""
        return self.has_confirmed

    @property
    def has_match_verified_stale_only(self) -> bool:
        return not self.has_confirmed and bool(self.stale_offers)


def _one_per_shop(offers: list[Offer]) -> list[Offer]:
    by_shop: dict[str, Offer] = {}
    for offer in offers:
        if not offer.in_stock:
            continue
        shop = offer.shop_name or ""
        prev = by_shop.get(shop)
        if prev is None or (offer.price_pln or 0) < (prev.price_pln or 0):
            by_shop[shop] = offer
    return sorted(by_shop.values(), key=lambda o: o.price_pln or float("inf"))


def _peer_prices(game_offers: list[Offer], *, game_title: str | None) -> list[float]:
    return [
        float(o.price_pln)
        for o in game_offers
        if o.price_pln
        and o.price_pln > 0
        and (o.shop_name or "") not in {"Steam", "Steam US", "PlayStation Store", "Xbox Store"}
        and offer_edition_verified(o, game_title=game_title)
    ]


def _classify_offer_row(
    offer: Offer,
    game: Game,
    *,
    steam_price: float | None,
    peer_prices: list[float],
    now: datetime | None,
) -> PriceEngineOfferRow:
    match = evaluate_product_match(
        offer, game, steam_price_pln=steam_price, peer_prices=peer_prices, now=now
    )
    fresh = evaluate_offer_freshness_snapshot(offer, now=now)

    if match.status == MatchStatus.VERIFIED_MISMATCH:
        reason: ExclusionReason = "match_mismatch"
        if not match.url_ok:
            reason = "url_invalid"
        elif match.reason in {"peer_price_outlier", "expensive_vs_steam", "too_cheap_vs_steam"}:
            reason = "price_anomaly"
        elif match.reason == "low_match_confidence":
            reason = "low_confidence"
        elif not match.edition_ok:
            reason = "edition_mismatch"
        return PriceEngineOfferRow(offer, match.status, fresh.status, "excluded", reason)

    if match.status == MatchStatus.INSUFFICIENT_DATA:
        return PriceEngineOfferRow(offer, match.status, fresh.status, "excluded", "insufficient_data")

    title = game.title
    is_free = bool(getattr(game, "is_free", False))
    if not offer_eligible_for_best_price(
        offer,
        steam_price_pln=steam_price,
        peer_prices=peer_prices,
        game_title=title,
        now=now,
        require_fresh=False,
        allow_zero_price=is_free,
    ):
        return PriceEngineOfferRow(offer, match.status, fresh.status, "excluded", "not_eligible")

    if match.status == MatchStatus.VERIFIED_MATCH and fresh.is_confirmed_fresh:
        if offer_is_confirmed_for_display(
            offer,
            game,
            steam_price_pln=steam_price,
            peer_prices=peer_prices,
            now=now,
        ):
            return PriceEngineOfferRow(offer, match.status, fresh.status, "confirmed", None)

    if match.status == MatchStatus.VERIFIED_MATCH:
        return PriceEngineOfferRow(offer, match.status, fresh.status, "stale", "stale")

    return PriceEngineOfferRow(offer, match.status, fresh.status, "excluded", "not_eligible")


def _reference_steam_price_pl(offers: list[Offer], *, region: str) -> float | None:
    """Steam PLN reference for match/outlier gates — independent of US shopping visibility."""
    region = normalize_shopping_region(region)
    preferred = steam_shop_for_region(region)
    for shop in (preferred, "Steam", "Steam US"):
        row = next(
            (
                o
                for o in offers
                if o.shop_name == shop and o.in_stock and o.price_pln is not None and o.price_pln > 0
            ),
            None,
        )
        if row is not None:
            return float(row.price_pln)
    return None


def get_best_confirmed_offer(
    game: Game,
    offers: list[Offer],
    *,
    region: str = "pl",
    now: datetime | None = None,
) -> Offer | None:
    return evaluate_game_prices(game, offers, region=region, now=now).best_confirmed_offer


def get_best_verified_offer(
    game: Game,
    offers: list[Offer],
    *,
    region: str = "pl",
    now: datetime | None = None,
) -> Offer | None:
    return get_best_confirmed_offer(game, offers, region=region, now=now)


def evaluate_game_prices(
    game: Game,
    offers: list[Offer],
    *,
    region: str = "pl",
    now: datetime | None = None,
) -> PriceEngineResult:
    region = normalize_shopping_region(region)
    now = now or datetime.utcnow()
    allowed = display_shops_for_game(game, region=region)
    is_free = bool(getattr(game, "is_free", False))
    steam_shop = steam_shop_for_region(region)

    visible: list[Offer] = []
    for offer in offers:
        if offer.shop_name not in allowed:
            continue
        if not offer_visible_for_shopping_region(offer, region):
            continue
        if (offer.price_pln or 0) <= 0 and not is_free:
            continue
        visible.append(offer)

    deduped = _one_per_shop(visible)
    steam_offer = next((o for o in deduped if o.shop_name == steam_shop and o.in_stock), None)
    if steam_offer is None and region == "us":
        steam_offer = next((o for o in deduped if o.shop_name == "Steam" and o.in_stock), None)
    steam_price = _reference_steam_price_pl(offers, region=region)
    peers = _peer_prices(deduped, game_title=game.title)

    rows = [
        _classify_offer_row(o, game, steam_price=steam_price, peer_prices=peers, now=now)
        for o in deduped
    ]
    confirmed = [r.offer for r in rows if r.bucket == "confirmed"]
    stale = [r.offer for r in rows if r.bucket == "stale"]
    excluded = [r.offer for r in rows if r.bucket == "excluded"]
    reasons = {r.offer.id: r.exclusion_reason for r in rows if r.exclusion_reason and r.offer.id}

    prefer_epic = is_free and prefer_epic_over_steam_for_free(getattr(game, "steam_appid", None))

    def _pick_min(candidates: list[Offer]) -> Offer | None:
        pool = list(candidates)
        if prefer_epic:
            pool = [o for o in pool if o.shop_name != "Steam"] or pool
        if not pool:
            return None
        pool.sort(key=lambda o: (o.price_pln if o.price_pln is not None else float("inf"), o.shop_name or ""))
        if prefer_epic:
            epic = next((o for o in pool if o.shop_name == "Epic Games"), None)
            if epic:
                return epic
        return pool[0]

    best_confirmed = _pick_min(confirmed)
    best_price = (
        float(best_confirmed.price_pln) if best_confirmed and best_confirmed.price_pln is not None else None
    )

    last_candidates = [
        o
        for o in deduped
        if evaluate_product_match(o, game, steam_price_pln=steam_price, peer_prices=peers, now=now).status
        == MatchStatus.VERIFIED_MATCH
        and offer_eligible_for_best_price(
            o,
            steam_price_pln=steam_price,
            peer_prices=peers,
            game_title=game.title,
            now=now,
            require_fresh=False,
            allow_zero_price=is_free,
        )
    ]
    last_known = None
    if last_candidates:
        last_candidates.sort(key=lambda o: o.price_pln or float("inf"))
        last_known = last_candidates[0]

    recommended, rec_reason = _pick_recommended(
        game,
        confirmed,
        best_confirmed,
        steam_price=steam_price,
        prefer_epic=prefer_epic,
    )

    last_checked = None
    for pool in (confirmed, stale, deduped):
        ts = max((o.updated_at for o in pool if o.updated_at), default=None)
        if ts and (last_checked is None or ts > last_checked):
            last_checked = ts

    unavail_msg = None
    if not best_confirmed:
        unavail_msg = confirmed_unavailable_pl(
            last_checked=format_last_checked_pl(last_checked)
        )

    return PriceEngineResult(
        game_id=game.id,
        region=region,
        snapshot_at=now,
        best_confirmed_offer=best_confirmed,
        best_confirmed_price=best_price,
        best_verified_offer=best_confirmed,
        best_verified_price=best_price,
        recommended_offer=recommended,
        recommended_reason=rec_reason,
        last_known_offer=last_known,
        last_known_price=float(last_known.price_pln) if last_known and last_known.price_pln is not None else None,
        confirmed_offers=confirmed,
        stale_offers=stale,
        excluded=excluded,
        exclusion_reasons=reasons,
        rows=rows,
        last_checked_label=format_last_checked_pl(last_checked),
        confirmed_unavailable_message=unavail_msg,
    )


def _pick_recommended(
    game: Game,
    confirmed: list[Offer],
    best: Offer | None,
    *,
    steam_price: float | None,
    prefer_epic: bool,
) -> tuple[Offer | None, str | None]:
    if not confirmed:
        return None, None
    if prefer_epic:
        epic = next((o for o in confirmed if o.shop_name == "Epic Games"), None)
        if epic:
            return epic, "verified_f2p_storefront"
    if best is None:
        return None, None
    best_price = float(best.price_pln or 0)
    if best.shop_name in _OFFICIAL_TRUST_SHOPS:
        return best, "verified_official_min"
    officials = [o for o in confirmed if o.shop_name in _OFFICIAL_TRUST_SHOPS and (o.price_pln or 0) > 0]
    if officials and best_price > 0:
        officials.sort(key=lambda o: o.price_pln or float("inf"))
        off = officials[0]
        off_price = float(off.price_pln or 0)
        if off_price <= best_price * (1 + _RECOMMENDED_OFFICIAL_TOLERANCE):
            return off, "official_within_tolerance"
    return best, "confirmed_min"


def evaluate_game_prices_from_db(
    db: Session,
    game: Game,
    *,
    region: str = "pl",
    now: datetime | None = None,
) -> PriceEngineResult:
    offers = (
        db.query(Offer)
        .filter(
            Offer.game_id == game.id,
            Offer.in_stock == True,  # noqa: E712
            Offer.price_pln.isnot(None),
        )
        .all()
    )
    return evaluate_game_prices(game, offers, region=region, now=now)


def best_offers_map_v2(
    db: Session,
    game_ids: list[int],
    *,
    region: str = "pl",
    games: dict[int, Game] | None = None,
    now: datetime | None = None,
) -> dict[int, Offer]:
    if not game_ids:
        return {}
    if games is None:
        games = {g.id: g for g in db.query(Game).filter(Game.id.in_(game_ids)).all()}
    out: dict[int, Offer] = {}
    for gid in game_ids:
        game = games.get(gid)
        if not game:
            continue
        result = evaluate_game_prices_from_db(db, game, region=region, now=now)
        if result.best_confirmed_offer:
            out[gid] = result.best_confirmed_offer
    return out


def unverified_offers_from_result(
    engine_result: PriceEngineResult | None,
) -> list[tuple[Offer, str | None]]:
    """In-stock excluded rows for a separate UI category (not used for best price)."""
    if engine_result is None:
        return []
    display_ids = {
        o.id
        for o in list(engine_result.confirmed_offers) + list(engine_result.stale_offers)
    }
    out: list[tuple[Offer, str | None]] = []
    seen: set[int] = set()
    for row in engine_result.rows or []:
        offer = row.offer
        if offer is None or offer.id in display_ids or offer.id in seen:
            continue
        if row.bucket != "excluded":
            continue
        if not offer.in_stock or offer.price_pln is None or offer.price_pln <= 0:
            continue
        reason = row.exclusion_reason
        reason_s = reason.value if hasattr(reason, "value") else (str(reason) if reason else None)
        seen.add(offer.id)
        out.append((offer, reason_s))
    out.sort(key=lambda item: float(item[0].price_pln or 0))
    return out


def result_to_audit_dict(result: PriceEngineResult) -> dict[str, Any]:
    def _offer(o: Offer | None) -> dict[str, Any] | None:
        if o is None:
            return None
        return {
            "id": o.id,
            "shop_name": o.shop_name,
            "price_pln": o.price_pln,
            "updated_at": o.updated_at.isoformat() if o.updated_at else None,
            "match_confidence": o.match_confidence,
        }

    return {
        "game_id": result.game_id,
        "region": result.region,
        "snapshot_at": result.snapshot_at.isoformat(),
        "best_confirmed": _offer(result.best_confirmed_offer),
        "best_confirmed_price": result.best_confirmed_price,
        "best_verified": _offer(result.best_verified_offer),
        "recommended": _offer(result.recommended_offer),
        "recommended_reason": result.recommended_reason,
        "last_known": _offer(result.last_known_offer),
        "counts": {
            "confirmed": len(result.confirmed_offers),
            "stale": len(result.stale_offers),
            "excluded": len(result.excluded),
        },
        "rows": [
            {
                "offer_id": r.offer.id,
                "shop": r.offer.shop_name,
                "price_pln": r.offer.price_pln,
                "bucket": r.bucket,
                "match_status": r.match_status.value,
                "freshness": r.freshness_status,
                "exclusion": r.exclusion_reason,
            }
            for r in result.rows
        ],
    }
