"""One-shot audit of verified-new candidates from discovery_latest.json."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORT = ROOT / "reports" / "discovery_latest.json"


def main() -> None:
    data = json.loads(REPORT.read_text(encoding="utf-8"))
    cands = data.get("candidates") or []
    new = [
        c
        for c in cands
        if (c.get("match") or {}).get("status") == "new_candidate"
        and (c.get("steam_resolution") or {}).get("status") == "verified"
    ]
    print(f"verified_new={len(new)}")
    print("buckets", dict(Counter((c.get("review") or {}).get("bucket") for c in new)))
    print("reasons:")
    for k, v in Counter((c.get("review") or {}).get("reason") for c in new).most_common():
        print(f"  {v:3d}  {k}")
    print("categories:")
    for k, v in Counter(
        (c.get("popularity") or {}).get("category") for c in new
    ).most_common():
        print(f"  {v:3d}  {k}")

    print("\n=== APPROVABLE ===")
    for c in new:
        if (c.get("review") or {}).get("bucket") != "APPROVABLE":
            continue
        steam = c.get("steam") or {}
        pop = c.get("popularity") or {}
        print(
            c.get("name"),
            "igdb",
            c.get("igdb_id"),
            "appid",
            c.get("steam_appid"),
            "cat",
            pop.get("category"),
            "recs",
            steam.get("recommendations"),
            "norm",
            pop.get("metric_norm"),
            "free",
            steam.get("is_free"),
        )

    # Why popular/trending land in NEEDS_REVIEW
    print("\n=== NEEDS_REVIEW by category ===")
    for c in new:
        if (c.get("review") or {}).get("bucket") != "NEEDS_REVIEW":
            continue
        pop = c.get("popularity") or {}
        steam = c.get("steam") or {}
        rev = c.get("review") or {}
        print(
            pop.get("category"),
            "|",
            c.get("name")[:40],
            "|",
            rev.get("reason"),
            "| recs=",
            steam.get("recommendations"),
            "norm=",
            pop.get("metric_norm"),
            "free=",
            steam.get("is_free"),
            "coming=",
            steam.get("coming_soon"),
        )


if __name__ == "__main__":
    main()
