"""CLI entry: python -m app.jobs.deal_candidates [--dry-run] [--limit N]."""
from __future__ import annotations

import argparse
import json
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan Deal Candidates (never auto-publishes).")
    parser.add_argument("--dry-run", action="store_true", help="Detect without writing candidates")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--top", type=int, default=10, help="Print top N sample events after scan")
    args = parser.parse_args(argv)

    from app.core.database import SessionLocal, init_db
    from app.core.discover_candidates import list_candidates, reason_text_for, scan_deal_candidates
    from app.core.schema_migrate import ensure_sqlite_schema
    from app.models.models import Game

    init_db()
    ensure_sqlite_schema()
    db = SessionLocal()
    try:
        stats = scan_deal_candidates(db, limit=args.limit, dry_run=args.dry_run)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        if not args.dry_run and args.top > 0:
            rows = list_candidates(db, status="open", limit=args.top)
            samples = []
            for r in rows:
                game = db.query(Game).filter(Game.id == r.game_id).first()
                samples.append(
                    {
                        "game": game.title if game else r.game_id,
                        "store": r.shop_name,
                        "current": r.price_current,
                        "previous": r.price_previous,
                        "discount": r.discount_percent,
                        "type": r.reason,
                        "score": r.score,
                        "reason": reason_text_for(r),
                    }
                )
            print(json.dumps({"top": samples}, ensure_ascii=False, indent=2))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
