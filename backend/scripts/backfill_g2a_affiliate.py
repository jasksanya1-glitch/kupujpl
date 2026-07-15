#!/usr/bin/env python3
"""Re-apply G2A Goldmine affiliate params to all G2A offers in DB."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.affiliate import make_affiliate_link
from app.core.database import SessionLocal
from app.models.models import Offer


def main() -> int:
    db = SessionLocal()
    try:
        offers = db.query(Offer).filter(Offer.shop_name == "G2A").all()
        updated = 0
        for offer in offers:
            base = offer.affiliate_url.split("?", 1)[0]
            if not base.startswith("http"):
                continue
            new_url = make_affiliate_link(base, "G2A")
            if new_url != offer.affiliate_url:
                offer.affiliate_url = new_url
                updated += 1
        db.commit()
        print(f"G2A offers: {len(offers)}, updated: {updated}")
        if offers:
            sample = make_affiliate_link(offers[0].affiliate_url.split("?", 1)[0], "G2A")
            print(f"sample: {sample[:140]}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
