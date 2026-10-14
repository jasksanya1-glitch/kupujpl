#!/usr/bin/env python3
"""Catalogue consistency audit (READ-ONLY by default).

Usage:
  python -m scripts.audit_catalog_data
  python -m scripts.audit_catalog_data --sample 200
  python -m scripts.audit_catalog_data --repair-rollups
  python -m scripts.audit_catalog_data --repair-rollups --repair-limit 500

Day-over-day jump diagnostics (also READ-ONLY):
  python -m scripts.audit_price_anomalies --sample 800

--repair-rollups rebuilds lowest_ever / avg_30d from eligible offers+snapshots.
Does not delete offers or snapshots.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.database import SessionLocal  # noqa: E402
from app.core.db_retry import commit_with_retry  # noqa: E402
from app.core.game_offer_selection import best_offers_map  # noqa: E402
from app.core.price_history import update_game_price_rollups  # noqa: E402
from app.core.seo_landings import SeoLanding, collect_landing_items  # noqa: E402
from app.models.models import Game, Offer  # noqa: E402
from app.schemas.schemas import GameListResponse  # noqa: E402

PRICE_EPS = 0.009


@dataclass
class AuditReport:
    games_checked: int = 0
    with_quality_best: int = 0
    with_raw_only: int = 0
    raw_vs_quality_mismatch: int = 0
    current_lt_historical_min: int = 0
    historical_min_nonpositive: int = 0
    current_nonpositive: int = 0
    avg_30d_nonpositive: int = 0
    discount_out_of_range: int = 0
    discount_missing_reference: int = 0
    budget30_mismatches: list[dict] = field(default_factory=list)
    promocje_mismatches: list[dict] = field(default_factory=list)
    sample_mismatches: list[dict] = field(default_factory=list)
    extreme_discounts: list[dict] = field(default_factory=list)
    rollups_repaired: int = 0


def _build_item(game: Game, best: Offer | None, steam: Offer | None) -> GameListResponse:
    steam_price = float(steam.price_pln) if steam and steam.price_pln else None
    best_price = float(best.price_pln) if best and best.price_pln else None
    savings_pct = None
    if steam_price and best_price and best_price < steam_price and steam_price > 0:
        savings_pct = int(round(((steam_price - best_price) / steam_price) * 100))
        if savings_pct < 0 or savings_pct > 99:
            savings_pct = None
    return GameListResponse(
        id=game.id,
        title=game.title or "",
        slug=game.slug or "",
        cover_image=game.cover_image,
        steam_appid=game.steam_appid,
        platform=getattr(game, "platform", None) or "pc",
        best_price_pln=best_price,
        best_shop_name=best.shop_name if best else None,
        best_price_is_official=bool(best.is_official) if best else None,
        steam_price_pln=steam_price,
        savings_pct=savings_pct,
        lowest_ever_pln=getattr(game, "lowest_ever_pln", None),
        avg_best_price_30d=getattr(game, "avg_best_price_30d", None),
    )


def audit(
    sample: int | None = None,
    budget_landing: bool = True,
    *,
    repair_rollups: bool = False,
    repair_limit: int | None = None,
) -> AuditReport:
    report = AuditReport()
    db = SessionLocal()
    try:
        q = db.query(Game).filter(Game.slug.isnot(None), Game.slug != "")
        if sample:
            games = q.order_by(Game.id.asc()).limit(sample).all()
        else:
            games = q.order_by(Game.id.asc()).all()
        report.games_checked = len(games)
        repaired = 0
        for i in range(0, len(games), 80):
            batch = games[i : i + 80]
            ids = [g.id for g in batch]
            games_by_id = {g.id: g for g in batch}
            quality = best_offers_map(db, ids, region="pl", games=games_by_id)
            raw_offers = (
                db.query(Offer)
                .filter(
                    Offer.game_id.in_(ids),
                    Offer.in_stock.is_(True),
                    Offer.price_pln.isnot(None),
                    Offer.price_pln > 0,
                )
                .all()
            )
            raw_best: dict[int, Offer] = {}
            for o in raw_offers:
                prev = raw_best.get(o.game_id)
                if prev is None or o.price_pln < prev.price_pln:
                    raw_best[o.game_id] = o

            for g in batch:
                qb = quality.get(g.id)
                rb = raw_best.get(g.id)
                if qb:
                    report.with_quality_best += 1
                    cur = float(qb.price_pln)
                    if cur <= 0:
                        report.current_nonpositive += 1
                    low = getattr(g, "lowest_ever_pln", None)
                    needs_repair = False
                    if low is not None:
                        if float(low) <= 0:
                            report.historical_min_nonpositive += 1
                            needs_repair = True
                        elif cur + PRICE_EPS < float(low):
                            report.current_lt_historical_min += 1
                            needs_repair = True
                        elif float(low) + PRICE_EPS < cur:
                            # historical min below current quality best → likely
                            # Steam US / marketplace outlier baked into rollups
                            needs_repair = True
                    else:
                        needs_repair = True
                    if repair_rollups and needs_repair and (
                        repair_limit is None or repaired < repair_limit
                    ):
                        update_game_price_rollups(db, g.id, region="pl")
                        repaired += 1
                    avg = getattr(g, "avg_best_price_30d", None)
                    if avg is not None and float(avg) <= 0:
                        report.avg_30d_nonpositive += 1
                    steam = next(
                        (
                            o
                            for o in raw_offers
                            if o.game_id == g.id and o.shop_name == "Steam"
                        ),
                        None,
                    )
                    if steam and steam.price_pln and qb.price_pln < steam.price_pln:
                        if float(steam.price_pln) <= 0 or float(qb.price_pln) <= 0:
                            report.discount_missing_reference += 1
                        else:
                            pct = int(
                                round(
                                    (float(steam.price_pln) - float(qb.price_pln))
                                    / float(steam.price_pln)
                                    * 100
                                )
                            )
                            if pct < 0 or pct > 99:
                                report.discount_out_of_range += 1
                elif rb:
                    report.with_raw_only += 1

                if qb and rb and abs(float(qb.price_pln) - float(rb.price_pln)) > PRICE_EPS:
                    report.raw_vs_quality_mismatch += 1
                    if len(report.sample_mismatches) < 40:
                        report.sample_mismatches.append(
                            {
                                "slug": g.slug,
                                "title": g.title,
                                "raw": float(rb.price_pln),
                                "raw_shop": rb.shop_name,
                                "quality": float(qb.price_pln),
                                "quality_shop": qb.shop_name,
                            }
                        )

            if repair_rollups and repaired:
                commit_with_retry(db)

        report.rollups_repaired = repaired

        if budget_landing:
            for slug, kind, title, group, kwargs in (
                ("gry-pc-do-30-zl", "budget", "Gry PC do 30 zł", "cena", {"max_price": 30}),
                ("promocje", "promocje", "Promocje na gry PC", "inne", {"min_savings_pct": 5}),
            ):
                landing = SeoLanding(slug, kind, title, group, **kwargs)
                items = collect_landing_items(db, landing, build_item=_build_item, limit=60)
                bucket = (
                    report.budget30_mismatches
                    if kind == "budget"
                    else report.promocje_mismatches
                )
                for item in items:
                    g = db.query(Game).filter(Game.slug == item.slug).first()
                    if not g:
                        continue
                    qmap = best_offers_map(db, [g.id], region="pl")
                    qb = qmap.get(g.id)
                    if not qb or item.best_price_pln is None:
                        continue
                    if abs(float(item.best_price_pln) - float(qb.price_pln)) > PRICE_EPS:
                        bucket.append(
                            {
                                "slug": item.slug,
                                "landing": float(item.best_price_pln),
                                "canonical": float(qb.price_pln),
                                "shop": qb.shop_name,
                            }
                        )
                    if item.savings_pct is not None and item.savings_pct >= 90:
                        if len(report.extreme_discounts) < 40:
                            report.extreme_discounts.append(
                                {
                                    "slug": item.slug,
                                    "savings_pct": item.savings_pct,
                                    "best": float(item.best_price_pln),
                                    "steam": item.steam_price_pln,
                                }
                            )
    finally:
        db.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=int, default=0, help="Limit games checked (0=all)")
    ap.add_argument("--budget-landing", action="store_true", default=True)
    ap.add_argument("--no-budget-landing", action="store_true")
    ap.add_argument(
        "--repair-rollups",
        action="store_true",
        help="Rebuild lowest_ever/avg_30d for games where current < historical_min",
    )
    ap.add_argument(
        "--repair-limit",
        type=int,
        default=0,
        help="Max rollups to repair (0=all matching)",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    report = audit(
        sample=args.sample or None,
        budget_landing=not args.no_budget_landing,
        repair_rollups=args.repair_rollups,
        repair_limit=args.repair_limit or None,
    )
    if args.json:
        print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        print("=== audit_catalog_data ===")
        mode = "REPAIR" if args.repair_rollups else "READ-ONLY"
        print(f"mode: {mode}")
        for k, v in asdict(report).items():
            if k in {
                "sample_mismatches",
                "budget30_mismatches",
                "promocje_mismatches",
                "extreme_discounts",
            }:
                print(f"{k}: {len(v)} (showing up to 10)")
                for row in v[:10]:
                    print(" ", row)
            else:
                print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
