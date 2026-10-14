#!/usr/bin/env python3
"""READ-ONLY day-over-day price anomaly report.

Flags unusual jumps that may be real market moves OR missing offers / scraper gaps.
Does NOT mutate prices.

Usage:
  python -m scripts.audit_price_anomalies
  python -m scripts.audit_price_anomalies --sample 500 --json
  python -m scripts.audit_price_anomalies --days 3
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.core.game_offer_selection import best_offers_map, display_shops_for_region  # noqa: E402
from app.core.store_classification import StoreClass, classify_store  # noqa: E402
from app.models.models import Game, Offer, PriceSnapshot  # noqa: E402

INCREASE_PCT = 300.0
DECREASE_PCT = 80.0
MULTIPLIER_JUMP = 5.0


@dataclass
class Anomaly:
    game_id: int
    title: str
    slug: str
    previous_price: float
    current_price: float
    pct_change: float
    previous_best_store: str | None
    current_best_store: str | None
    previous_at: str | None
    current_at: str
    valid_offers_now: int
    reason: str


@dataclass
class AnomalyReport:
    games_checked: int = 0
    anomalies: list[Anomaly] = field(default_factory=list)
    increase_gt_300: int = 0
    decrease_gt_80: int = 0
    multiplier_gt_5x: int = 0
    marketplace_to_official: int = 0


def _day_best(
    snaps: list[PriceSnapshot],
) -> tuple[float | None, str | None, datetime | None]:
    best_price = None
    best_shop = None
    best_at = None
    for s in snaps:
        if s.price_pln is None or float(s.price_pln) <= 0:
            continue
        price = float(s.price_pln)
        if best_price is None or price < best_price:
            best_price = price
            best_shop = s.shop_name
            best_at = s.recorded_at
    return best_price, best_shop, best_at


def audit_anomalies(*, sample: int | None = None, lookback_days: int = 2) -> AnomalyReport:
    report = AnomalyReport()
    db = SessionLocal()
    try:
        display = list(display_shops_for_region("pl"))
        q = db.query(Game).filter(Game.slug.isnot(None), Game.slug != "")
        if sample:
            games = q.order_by(Game.steam_review_count.desc().nulls_last()).limit(sample).all()
        else:
            games = q.order_by(Game.id.asc()).all()
        report.games_checked = len(games)
        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        prev_start = today_start - timedelta(days=max(1, lookback_days))

        for i in range(0, len(games), 60):
            batch = games[i : i + 60]
            ids = [g.id for g in batch]
            quality = best_offers_map(db, ids, region="pl", games={g.id: g for g in batch})
            snaps = (
                db.query(PriceSnapshot)
                .filter(
                    PriceSnapshot.game_id.in_(ids),
                    PriceSnapshot.in_stock.is_(True),
                    PriceSnapshot.shop_name.in_(display),
                    PriceSnapshot.price_pln > 0,
                    PriceSnapshot.recorded_at >= prev_start,
                    PriceSnapshot.recorded_at < today_start,
                )
                .all()
            )
            by_game: dict[int, list[PriceSnapshot]] = {}
            for s in snaps:
                by_game.setdefault(s.game_id, []).append(s)

            offers_now = (
                db.query(Offer)
                .filter(
                    Offer.game_id.in_(ids),
                    Offer.in_stock.is_(True),
                    Offer.price_pln.isnot(None),
                    Offer.price_pln > 0,
                    Offer.shop_name.in_(display),
                )
                .all()
            )
            offer_count: dict[int, int] = {}
            for o in offers_now:
                offer_count[o.game_id] = offer_count.get(o.game_id, 0) + 1

            for g in batch:
                cur_offer = quality.get(g.id)
                if not cur_offer or cur_offer.price_pln is None:
                    continue
                current = float(cur_offer.price_pln)
                prev_price, prev_shop, prev_at = _day_best(by_game.get(g.id, []))
                if prev_price is None or prev_price <= 0:
                    continue
                pct = ((current - prev_price) / prev_price) * 100.0
                reasons: list[str] = []
                if pct >= INCREASE_PCT:
                    reasons.append("day_over_day_increase_gt_300pct")
                    report.increase_gt_300 += 1
                if pct <= -DECREASE_PCT:
                    reasons.append("day_over_day_decrease_gt_80pct")
                    report.decrease_gt_80 += 1
                if current >= prev_price * MULTIPLIER_JUMP:
                    reasons.append("current_gt_5x_previous")
                    report.multiplier_gt_5x += 1
                prev_class = classify_store(prev_shop)
                cur_class = classify_store(cur_offer.shop_name)
                if (
                    prev_class is StoreClass.MARKETPLACE
                    and cur_class is StoreClass.OFFICIAL_STORE
                    and current > prev_price * 1.5
                ):
                    reasons.append("marketplace_min_to_official_min")
                    report.marketplace_to_official += 1
                if not reasons:
                    continue
                report.anomalies.append(
                    Anomaly(
                        game_id=g.id,
                        title=g.title or "",
                        slug=g.slug or "",
                        previous_price=round(prev_price, 2),
                        current_price=round(current, 2),
                        pct_change=round(pct, 1),
                        previous_best_store=prev_shop,
                        current_best_store=cur_offer.shop_name,
                        previous_at=prev_at.isoformat() if prev_at else None,
                        current_at=now.isoformat(),
                        valid_offers_now=offer_count.get(g.id, 0),
                        reason=";".join(reasons),
                    )
                )
    finally:
        db.close()
    report.anomalies.sort(key=lambda a: abs(a.pct_change), reverse=True)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=800, help="Games to scan (0=all)")
    ap.add_argument("--days", type=int, default=2, help="Lookback days for previous best")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--limit", type=int, default=50, help="Max anomalies to print")
    args = ap.parse_args()
    report = audit_anomalies(
        sample=args.sample or None,
        lookback_days=args.days,
    )
    if args.json:
        payload = asdict(report)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("=== audit_price_anomalies (READ-ONLY) ===")
        print(f"games_checked: {report.games_checked}")
        print(f"anomalies: {len(report.anomalies)}")
        print(f"increase_gt_300: {report.increase_gt_300}")
        print(f"decrease_gt_80: {report.decrease_gt_80}")
        print(f"multiplier_gt_5x: {report.multiplier_gt_5x}")
        print(f"marketplace_to_official: {report.marketplace_to_official}")
        for row in report.anomalies[: args.limit]:
            print(
                f"  {row.slug}: {row.previous_price} ({row.previous_best_store}) -> "
                f"{row.current_price} ({row.current_best_store}) "
                f"[{row.pct_change}%] offers_now={row.valid_offers_now} :: {row.reason}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
