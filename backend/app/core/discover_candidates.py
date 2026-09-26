"""Deal Candidate Engine — creates DiscoverCandidate rows (never auto-publishes)."""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.articles import create_draft_from_candidate
from app.core.deals_channel import build_top_deals
from app.models.models import Article, DiscoverCandidate, Game, Offer

logger = logging.getLogger("discover_candidates")

COOLDOWN_HOURS = 36
SCORE_FREE = 50
SCORE_DROP_70 = 35
SCORE_DROP_50 = 25
SCORE_NEW_LOW = 30
SCORE_POPULAR = 20
SCORE_EXPIRING = 15


def _fingerprint(game_id: int, reason: str, shop: str | None, price: float | None) -> str:
    raw = f"{game_id}|{reason}|{(shop or '').lower()}|{round(price or 0, 2)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _title_templates(
    *,
    game_title: str,
    reason: str,
    price: float | None,
    prev: float | None,
    discount: int | None,
) -> tuple[str, str, str]:
    """Return (title, lead, article_type) — Polish suggestions only."""
    price_s = f"{price:.2f}".replace(".", ",") if price is not None else "?"
    prev_s = f"{prev:.2f}".replace(".", ",") if prev is not None else "?"
    disc = discount or 0
    if reason == "free_game":
        title = f"{game_title} za darmo. Gra normalnie kosztuje {prev_s} zł"
        lead = (
            f"{game_title} jest obecnie dostępne za 0 zł. "
            f"Wcześniejsza cena w naszym porównaniu to {prev_s} zł. Oferta może być ograniczona czasowo."
        )
        return title, lead, "free_game"
    if reason == "expiring_soon":
        title = f"Ostatnia szansa na {game_title} za {price_s} zł. Promocja wkrótce się kończy"
        lead = (
            f"Według danych KupujPL promocja na {game_title} zbliża się do końca. "
            f"Aktualna cena to {price_s} zł."
        )
        return title, lead, "deal"
    if reason == "new_low":
        title = f"{game_title} w jednej z najniższych cen zarejestrowanych przez KupujPL — {price_s} zł"
        lead = (
            f"{game_title} kosztuje teraz {price_s} zł — to jedna z najniższych cen "
            f"zarejestrowanych przez KupujPL (nie mylić z historycznym minimum rynku)."
        )
        return title, lead, "price_drop"
    if disc >= 70:
        title = f"Duża promocja na {game_title}. Cena spadła do {price_s} zł (−{disc}%)"
        lead = f"{game_title} przecenione o {disc}%. Aktualna cena to {price_s} zł (wcześniej ok. {prev_s} zł)."
        return title, lead, "deal"
    title = f"{game_title} przecenione o {disc}%. Aktualna cena to {price_s} zł"
    lead = f"Aktualna cena {game_title} w porównaniu KupujPL to {price_s} zł (−{disc}% względem wyższej oferty)."
    return title, lead, "price_drop"


def _content_html(game: Game, lead: str, shop: str | None, price: float | None) -> str:
    parts = [f"<p>{lead}</p>"]
    if shop and price is not None:
        parts.append(
            f"<p>Najkorzystniejsza oferta w naszym skanie: <strong>{shop}</strong> — "
            f"<strong>{price:.2f} zł</strong>.</p>"
        )
    parts.append(
        f'<p><a href="/games/gra/{game.slug}">Sprawdź aktualne ceny {game.title} w KupujPL Games</a>.</p>'
    )
    return "\n".join(parts)


def scan_deal_candidates(db: Session, *, limit: int = 80) -> dict[str, int]:
    """Detect candidates from top deals + free/new-low heuristics. No publish."""
    created = 0
    updated = 0
    skipped = 0
    cooldown_since = datetime.utcnow() - timedelta(hours=COOLDOWN_HOURS)

    deals = build_top_deals(db, limit=limit, min_savings_pct=50)
    for item, offer in deals:
        game = db.query(Game).filter(Game.id == item.id).first()
        if not game or not offer:
            continue
        discount = int(item.savings_pct or 0)
        reasons: list[tuple[str, int]] = []
        if discount >= 70:
            reasons.append(("price_drop_70", SCORE_DROP_70))
        elif discount >= 50:
            reasons.append(("price_drop_50", SCORE_DROP_50))
        if game.lowest_ever_pln is not None and offer.price_pln is not None:
            if offer.price_pln + 0.05 < game.lowest_ever_pln:
                reasons.append(("new_low", SCORE_NEW_LOW))
        if (game.steam_review_count or 0) >= 5000 or (game.steam_recommendations or 0) >= 5000:
            if discount >= 50:
                reasons.append(("popular_drop", SCORE_POPULAR))

        for reason, base_score in reasons:
            score = base_score
            if reason.startswith("price_drop") and (
                (game.steam_review_count or 0) >= 5000
            ):
                score += SCORE_POPULAR
            fp = _fingerprint(game.id, reason, offer.shop_name, offer.price_pln)
            existing = db.query(DiscoverCandidate).filter(DiscoverCandidate.fingerprint == fp).first()
            if existing:
                if existing.status == "ignored":
                    skipped += 1
                    continue
                if existing.detected_at and existing.detected_at > cooldown_since:
                    skipped += 1
                    continue
                existing.score = max(existing.score or 0, score)
                existing.price_current = offer.price_pln
                existing.price_previous = item.steam_price_pln
                existing.discount_percent = discount
                existing.updated_at = datetime.utcnow()
                updated += 1
                continue
            recent_same = (
                db.query(DiscoverCandidate)
                .filter(
                    DiscoverCandidate.game_id == game.id,
                    DiscoverCandidate.reason == reason,
                    DiscoverCandidate.detected_at >= cooldown_since,
                )
                .first()
            )
            if recent_same:
                skipped += 1
                continue
            row = DiscoverCandidate(
                fingerprint=fp,
                game_id=game.id,
                reason=reason,
                score=score,
                shop_name=offer.shop_name,
                price_current=offer.price_pln,
                price_previous=item.steam_price_pln,
                discount_percent=discount,
                status="open",
                payload_json=json.dumps(
                    {"game_slug": game.slug, "game_title": game.title},
                    ensure_ascii=False,
                ),
            )
            db.add(row)
            created += 1

    # Free games that still have a paid Steam reference (best offer ~0)
    free_offers = (
        db.query(Offer, Game)
        .join(Game, Game.id == Offer.game_id)
        .filter(
            Offer.in_stock.is_(True),
            Offer.price_pln <= 0.01,
            Game.is_free.is_(False),
        )
        .limit(40)
        .all()
    )
    for offer, game in free_offers:
        reason = "free_game"
        fp = _fingerprint(game.id, reason, offer.shop_name, 0.0)
        if db.query(DiscoverCandidate).filter(DiscoverCandidate.fingerprint == fp).first():
            skipped += 1
            continue
        recent = (
            db.query(DiscoverCandidate)
            .filter(
                DiscoverCandidate.game_id == game.id,
                DiscoverCandidate.reason == reason,
                DiscoverCandidate.detected_at >= cooldown_since,
            )
            .first()
        )
        if recent:
            skipped += 1
            continue
        prev = None
        paid = (
            db.query(Offer)
            .filter(
                Offer.game_id == game.id,
                Offer.in_stock.is_(True),
                Offer.price_pln > 1,
            )
            .order_by(Offer.price_pln.asc())
            .first()
        )
        if paid:
            prev = paid.price_pln
        db.add(
            DiscoverCandidate(
                fingerprint=fp,
                game_id=game.id,
                reason=reason,
                score=SCORE_FREE,
                shop_name=offer.shop_name,
                price_current=0.0,
                price_previous=prev,
                discount_percent=100 if prev else None,
                status="open",
                payload_json=json.dumps(
                    {"game_slug": game.slug, "game_title": game.title},
                    ensure_ascii=False,
                ),
            )
        )
        created += 1

    db.commit()
    return {"created": created, "updated": updated, "skipped": skipped}


def list_candidates(
    db: Session,
    *,
    status: str | None = "open",
    reason: str | None = None,
    limit: int = 100,
) -> list[DiscoverCandidate]:
    q = db.query(DiscoverCandidate).order_by(
        DiscoverCandidate.score.desc(),
        DiscoverCandidate.detected_at.desc(),
    )
    if status:
        q = q.filter(DiscoverCandidate.status == status)
    if reason:
        if reason == "70+":
            q = q.filter(DiscoverCandidate.discount_percent >= 70)
        elif reason == "50+":
            q = q.filter(DiscoverCandidate.discount_percent >= 50)
        else:
            q = q.filter(DiscoverCandidate.reason == reason)
    return q.limit(limit).all()


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
    row = db.query(DiscoverCandidate).filter(DiscoverCandidate.id == cand_id).first()
    if not row or row.status == "ignored":
        return None
    game = db.query(Game).filter(Game.id == row.game_id).first()
    if not game:
        return None
    title, lead, atype = _title_templates(
        game_title=game.title,
        reason=row.reason,
        price=row.price_current,
        prev=row.price_previous,
        discount=row.discount_percent,
    )
    content = _content_html(game, lead, row.shop_name, row.price_current)
    art = create_draft_from_candidate(
        db,
        game=game,
        reason=row.reason,
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
    row.status = "drafted"
    row.article_id = art.id
    row.updated_at = datetime.utcnow()
    db.commit()
    return art
