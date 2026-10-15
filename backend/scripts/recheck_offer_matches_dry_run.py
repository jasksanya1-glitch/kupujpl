"""Dry-run re-check of keyshop offers against improved title matching.

Default: report only (no DB writes).
Use --apply to soft-disable bad offers (in_stock=False). Does not delete rows
or history. Always write a JSON report for audit/rollback review.

Usage:
  PYTHONPATH=. python scripts/recheck_offer_matches_dry_run.py
  PYTHONPATH=. python scripts/recheck_offer_matches_dry_run.py --apply
  PYTHONPATH=. python scripts/recheck_offer_matches_dry_run.py --slug resonance-a-plague-tale-legacy-2713000
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.core.db_retry import commit_with_retry
from app.models.models import Game, Offer
from app.parsers.keyshop_common import classify_keyshop_product, product_title_from_url

# Keyshops + official digi stores that still use title/URL matching (not Steam AppID).
CHECKED_SHOPS = {
    "Instant Gaming",
    "Kinguin",
    "G2A",
    "CDKeys",
    "Gamivo",
    "Fanatical",
    "Eneba",
    "GOG",
    "Epic Games",
}

# Steam / console storefronts keyed by AppID or catalog ID — skip title recheck.
ID_BACKED_SHOPS = {"Steam", "Steam US", "PlayStation Store", "Xbox Store"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Recheck keyshop offer matches (dry-run by default)")
    parser.add_argument("--apply", action="store_true", help="Set in_stock=False on bad keyshop rows")
    parser.add_argument("--slug", default="", help="Limit to one game slug")
    parser.add_argument(
        "--report",
        default="",
        help="JSON report path (default: tmp/offer_recheck_<ts>.json)",
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        q = (
            db.query(Game, Offer)
            .join(Offer, Offer.game_id == Game.id)
            .filter(Offer.in_stock == True)  # noqa: E712
        )
        if args.slug:
            q = q.filter(Game.slug == args.slug)
        rows = q.all()

        bad: list[dict] = []
        f2p_paid: list[dict] = []
        checked = 0
        for game, offer in rows:
            checked += 1
            shop = offer.shop_name or ""
            if bool(game.is_free) and shop not in ID_BACKED_SHOPS and (offer.price_pln or 0) > 0:
                f2p_paid.append(
                    {
                        "game_id": game.id,
                        "slug": game.slug,
                        "title": game.title,
                        "is_free": True,
                        "offer_id": offer.id,
                        "shop": shop,
                        "price_pln": offer.price_pln,
                        "url": offer.affiliate_url,
                        "reason": "f2p_paid_keyshop",
                        "action": "soft_disable",
                    }
                )
            if shop not in CHECKED_SHOPS:
                continue
            candidate = product_title_from_url(offer.affiliate_url) or ""
            # Skip unusable URL titles (Awin pclick / Epic UUID / empty).
            cand_l = candidate.lower()
            cand_compact = "".join(ch for ch in cand_l if ch.isalnum())
            if (
                not candidate
                or "pclick.php" in cand_l
                or (
                    len(cand_compact) >= 16
                    and cand_compact.isalnum()
                    and any(ch.isdigit() for ch in cand_compact)
                    and sum(ch.isalpha() for ch in candidate) < 6
                )
                or ("audience" in cand_l and candidate.count(" ") < 1)
            ):
                url_l = (offer.affiliate_url or "").lower()
                if "innocence" in url_l and "legacy" in (game.title or "").lower():
                    bad.append(
                        {
                            "game_id": game.id,
                            "slug": game.slug,
                            "title": game.title,
                            "is_free": bool(game.is_free),
                            "offer_id": offer.id,
                            "shop": shop,
                            "price_pln": offer.price_pln,
                            "match_confidence": offer.match_confidence,
                            "candidate": candidate,
                            "url": offer.affiliate_url,
                            "reason": "url_title_mismatch",
                            "score": 0.0,
                            "action": "soft_disable",
                        }
                    )
                continue
            verdict = classify_keyshop_product(game.title, candidate, offer.affiliate_url)
            if not verdict.get("valid"):
                bad.append(
                    {
                        "game_id": game.id,
                        "slug": game.slug,
                        "title": game.title,
                        "is_free": bool(game.is_free),
                        "offer_id": offer.id,
                        "shop": shop,
                        "price_pln": offer.price_pln,
                        "match_confidence": offer.match_confidence,
                        "candidate": candidate,
                        "url": offer.affiliate_url,
                        "reason": verdict.get("reason"),
                        "score": verdict.get("score"),
                        "action": "soft_disable",
                    }
                )

        # Dedupe by offer_id (f2p_paid may overlap bad)
        by_id: dict[int, dict] = {}
        for item in bad + f2p_paid:
            by_id[int(item["offer_id"])] = item
        proposed = list(by_id.values())

        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        report_path = Path(args.report) if args.report else Path("tmp") / f"offer_recheck_{ts}.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "apply": bool(args.apply),
            "checked_offers": checked,
            "proposed_changes": len(proposed),
            "mismatch_or_low_score": len(bad),
            "f2p_paid_keyshops": len(f2p_paid),
            "items": proposed,
        }
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        print(
            f"checked={checked} proposed={len(proposed)} "
            f"mismatch={len(bad)} f2p_paid={len(f2p_paid)} apply={args.apply}"
        )
        print(f"report={report_path.resolve()}")
        for item in proposed[:40]:
            print(
                f"{item['action']}\t{item['reason']}\t{item['shop']}\t"
                f"{item['price_pln']}\t{item['slug']}\t{item.get('candidate') or ''}"
            )

        if args.apply and proposed:
            ids = [int(x["offer_id"]) for x in proposed]
            offers = db.query(Offer).filter(Offer.id.in_(ids)).all()
            for offer in offers:
                offer.in_stock = False
            commit_with_retry(db)
            print(f"soft_disabled={len(offers)}")
        elif args.apply:
            print("soft_disabled=0")
    finally:
        db.close()


if __name__ == "__main__":
    main()
