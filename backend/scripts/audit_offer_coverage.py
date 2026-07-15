"""Mass offer coverage audit/restore worker.

DB mode is meant for the VPS and can classify active/missing/hidden offers.
API mode is meant for the laptop/SP server and performs focused lookups for the
admin queue, then optionally uploads valid offers to /api/admin/offers/bulk.

Eneba is intentionally disabled in both modes.
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_SHOPS = (
    "Instant Gaming",
    "Kinguin",
    "CDKeys",
    "G2A",
    "Gamivo",
    "Fanatical",
    "GOG",
    "Epic Games",
)
FORBIDDEN_SHOPS = {"Eneba"}


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env_file(ROOT / "tools" / "scan_config.env")
os.environ.setdefault("GAMES_API_URL", "https://kupujpl.pl/games")
os.environ.setdefault("OFFER_FETCH_FAST", "1")
os.environ.setdefault("HTTP_FETCH_TIMEOUT", "12")
os.environ.setdefault("GAMIVO_429_RETRIES", "0")
os.environ.setdefault("GAMIVO_REQUEST_DELAY_SEC", "1.0")

# Keep Eneba disabled even if the remote config or local env changes.
disabled = {
    s.strip()
    for s in os.environ.get("OFFER_SCAN_DISABLED_SHOPS", "").split(",")
    if s.strip()
}
disabled.add("Eneba")
os.environ["OFFER_SCAN_DISABLED_SHOPS"] = ",".join(sorted(disabled))

from app.parsers.offer_fetch_remote import fetch_remote_offers  # noqa: E402
from app.parsers.shop_scan_stats import ShopScanStats  # noqa: E402
from app.parsers.keyshop_common import (  # noqa: E402
    classify_keyshop_product,
    product_title_from_url,
    upsert_keyshop_offer,
)

try:  # noqa: SIM105 - optional in API-only laptop mode
    from sqlalchemy.orm import selectinload

    from app.core.database import SessionLocal
    from app.core.db_retry import commit_with_retry
    from app.models.models import Game, Offer
    from app.parsers.tier_a_top5000 import build_tier_a_queue
except Exception:  # pragma: no cover - API-only environment
    SessionLocal = None  # type: ignore[assignment]
    commit_with_retry = None  # type: ignore[assignment]
    Game = None  # type: ignore[assignment]
    Offer = None  # type: ignore[assignment]
    build_tier_a_queue = None  # type: ignore[assignment]
    selectinload = None  # type: ignore[assignment]


ALL_AUDIT_SHOPS = ("Steam",) + DEFAULT_SHOPS
LOOKUP_SHOPS = tuple(shop for shop in DEFAULT_SHOPS if shop not in FORBIDDEN_SHOPS)


def _access_code() -> str:
    return (
        os.environ.get("PANEL3_ACCESS_CODE")
        or os.environ.get("PANEL3_CODE")
        or ""
    ).strip()


def _api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    api = os.environ["GAMES_API_URL"].rstrip("/")
    url = f"{api}/api/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-Panel3-Code": _access_code(),
            "User-Agent": f"KupujPL-CoverageAudit/{socket.gethostname()}",
        },
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_shops(raw: str | None) -> tuple[str, ...]:
    if not raw:
        shops = DEFAULT_SHOPS
    else:
        shops = tuple(s.strip() for s in raw.split(",") if s.strip())
    forbidden = FORBIDDEN_SHOPS & set(shops)
    if forbidden:
        raise SystemExit(f"Forbidden shops requested: {', '.join(sorted(forbidden))}")
    return tuple(s for s in shops if s not in FORBIDDEN_SHOPS)


def _is_keyshop(shop: str) -> bool:
    return shop in {"Instant Gaming", "Kinguin", "CDKeys", "G2A", "Gamivo", "Fanatical"}


def _offer_product_url(offer: Any) -> str:
    return str(getattr(offer, "affiliate_url", "") or "")


def _classify_existing_offer(game: Any, offer: Any) -> dict[str, Any]:
    shop = str(getattr(offer, "shop_name", "") or "")
    if shop == "Eneba":
        return {"state": "forbidden", "reason": "eneba_disabled", "score": 0.0}
    if not _is_keyshop(shop):
        if shop == "Steam":
            return {"state": "active" if getattr(offer, "in_stock", False) else "hidden_valid", "reason": "official", "score": 1.0}
        url = _offer_product_url(offer)
        title = product_title_from_url(url)
        verdict = classify_keyshop_product(str(game.title), title, url)
        state = "active" if getattr(offer, "in_stock", False) else "hidden_valid"
        if not verdict["valid"]:
            state = "active_invalid" if getattr(offer, "in_stock", False) else "hidden_invalid"
        return {
            "state": state,
            "reason": f"official_{verdict['reason']}",
            "score": round(float(verdict["score"]), 3),
            "candidate": title,
        }
    url = _offer_product_url(offer)
    title = product_title_from_url(url)
    verdict = classify_keyshop_product(str(game.title), title, url)
    state = "active" if getattr(offer, "in_stock", False) else "hidden_valid"
    if not verdict["valid"]:
        state = "active_invalid" if getattr(offer, "in_stock", False) else "hidden_invalid"
    return {
        "state": state,
        "reason": verdict["reason"],
        "score": round(float(verdict["score"]), 3),
        "candidate": title,
    }


def _classify_found_offer(game: dict[str, Any] | Any, offer: dict[str, Any]) -> dict[str, Any]:
    shop = str(offer.get("shop_name") or "")
    if shop == "Eneba":
        return {"valid": False, "reason": "eneba_disabled", "score": 0.0}
    title = getattr(game, "title", None) or game.get("title")  # type: ignore[union-attr]
    url = str(offer.get("product_url") or offer.get("affiliate_url") or "")
    if shop == "Steam":
        return {"valid": True, "reason": "steam_appid", "score": 1.0}
    if not _is_keyshop(shop):
        verdict = classify_keyshop_product(str(title or ""), product_title_from_url(url), url)
        return {
            "valid": bool(verdict["valid"]),
            "reason": f"official_{verdict['reason']}",
            "score": verdict["score"],
        }
    return classify_keyshop_product(str(title or ""), product_title_from_url(url), url)


def _queue(*, tier: str | None, limit: int) -> list[dict[str, Any]]:
    params = {"limit": str(limit)}
    if tier:
        params["tier"] = tier
    path = "admin/offers/queue?" + urllib.parse.urlencode(params)
    return list((_api("GET", path).get("items") or []))


def _db_games(*, tier: str, limit: int, skip: int) -> list[Any]:
    if SessionLocal is None or Game is None:
        raise SystemExit("DB mode is unavailable in this environment")
    db = SessionLocal()
    try:
        ids: list[int] = []
        if tier == "top5000" and build_tier_a_queue is not None:
            ids = [int(row["game_id"]) for row in build_tier_a_queue(db, limit=limit + max(0, skip)) if row.get("game_id")]
        if ids:
            ids = ids[skip : skip + limit]
            games = db.query(Game).options(selectinload(Game.offers)).filter(Game.id.in_(ids)).all()
            by_id = {int(game.id): game for game in games}
            return [by_id[i] for i in ids if i in by_id]
        query = db.query(Game).options(selectinload(Game.offers)).order_by(Game.steam_recommendations.desc().nullslast(), Game.id.asc())
        return query.offset(max(0, skip)).limit(limit).all()
    finally:
        db.close()


def _scan_one(
    idx: int,
    total: int,
    game: dict[str, Any],
    shops: tuple[str, ...],
    stats: ShopScanStats,
) -> dict[str, Any]:
    title = str(game.get("title") or "")
    slug = str(game.get("slug") or "")
    game_id = game.get("game_id")
    t0 = time.perf_counter()
    raw_offers = fetch_remote_offers(title, shops=shops, stats=stats, game_slug=slug)
    offers = []
    rejected = []
    for offer in raw_offers:
        if offer.get("shop_name") in FORBIDDEN_SHOPS:
            rejected.append({"shop": offer.get("shop_name"), "reason": "eneba_disabled"})
            continue
        verdict = _classify_found_offer(game, offer)
        if verdict["valid"]:
            offers.append(offer)
        else:
            rejected.append({"shop": offer.get("shop_name"), **verdict})
    elapsed = time.perf_counter() - t0
    names = ",".join(sorted({str(o.get("shop_name")) for o in offers})) or "-"
    return {
        "game_id": game_id,
        "title": title,
        "offers": offers,
        "rejected": rejected,
        "elapsed_sec": round(elapsed, 2),
        "line": f"[{idx}/{total}] {title[:64]} | {len(offers)} | {names} | {elapsed:.1f}s",
    }


def _db_scan_one(
    idx: int,
    total: int,
    game: Any,
    shops: tuple[str, ...],
    stats: ShopScanStats,
) -> dict[str, Any]:
    existing = {str(o.shop_name): o for o in getattr(game, "offers", []) if str(o.shop_name) not in FORBIDDEN_SHOPS}
    states: dict[str, dict[str, Any]] = {}
    updates: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    lookup_shops: list[str] = []

    for shop in shops:
        if shop == "Eneba":
            continue
        offer = existing.get(shop)
        if offer is None:
            states[shop] = {"state": "missing", "reason": "no_offer"}
            if shop in LOOKUP_SHOPS:
                lookup_shops.append(shop)
            continue
        verdict = _classify_existing_offer(game, offer)
        states[shop] = verdict
        if verdict["state"] == "hidden_valid":
            updates.append(
                {
                    "type": "restore_hidden",
                    "shop_name": shop,
                    "offer_id": int(offer.id),
                    "price_pln": float(offer.price_pln),
                    "product_url": _offer_product_url(offer),
                    "reason": verdict["reason"],
                }
            )
        if verdict["state"] in {"hidden_valid", "hidden_invalid", "active_invalid"}:
            examples.append(
                {
                    "state": verdict["state"],
                    "shop": shop,
                    "game": game.title,
                    "price_pln": getattr(offer, "price_pln", None),
                    "reason": verdict["reason"],
                    "candidate": verdict.get("candidate"),
                }
            )

    found_offers: list[dict[str, Any]] = []
    if lookup_shops:
        raw_offers = fetch_remote_offers(game.title, shops=tuple(lookup_shops), stats=stats, game_slug=game.slug)
        for offer in raw_offers:
            shop = str(offer.get("shop_name") or "")
            verdict = _classify_found_offer(game, offer)
            if verdict["valid"]:
                found_offers.append(offer)
                states[shop] = {"state": "missing_found", "reason": verdict["reason"], "score": verdict["score"]}
            else:
                states[shop] = {"state": "parser_rejected", "reason": verdict["reason"], "score": verdict["score"]}
                url = str(offer.get("product_url") or offer.get("affiliate_url") or "")
                examples.append(
                    {
                        "state": "parser_rejected",
                        "shop": shop,
                        "game": game.title,
                        "price_pln": offer.get("price_pln"),
                        "reason": verdict["reason"],
                        "candidate": product_title_from_url(url),
                    }
                )
        for shop in lookup_shops:
            if shop not in {o.get("shop_name") for o in raw_offers}:
                status = "parser_blocked" if stats.to_dict().get(shop, {}).get("errors") else "not_found"
                states[shop] = {"state": status, "reason": "lookup_empty"}

    if found_offers:
        updates.append({"type": "upsert_found", "game_id": int(game.id), "offers": found_offers})

    elapsed_states = ",".join(f"{shop}:{state['state']}" for shop, state in states.items() if state["state"] != "active")
    return {
        "game_id": int(game.id),
        "title": game.title,
        "states": states,
        "updates": updates,
        "examples": examples,
        "line": f"[{idx}/{total}] {game.title[:64]} | updates={len(updates)} | {elapsed_states or 'all_active'}",
    }


def _upload(updates: list[dict[str, Any]], *, chunk_size: int) -> dict[str, Any]:
    totals = {
        "games_touched": 0,
        "offers_upserted": 0,
        "errors": [],
        "chunks": 0,
    }
    source = f"coverage-audit:{socket.gethostname()}"
    for i in range(0, len(updates), chunk_size):
        chunk = updates[i : i + chunk_size]
        if not chunk:
            continue
        result = _api("POST", "admin/offers/bulk", {"source": source, "updates": chunk})
        totals["chunks"] += 1
        totals["games_touched"] += int(result.get("games_touched") or 0)
        totals["offers_upserted"] += int(result.get("offers_upserted") or 0)
        totals["errors"].extend(result.get("errors") or [])
    totals["errors"] = totals["errors"][:20]
    return totals


def _apply_db(rows: list[dict[str, Any]], *, chunk_size: int) -> dict[str, Any]:
    if SessionLocal is None or Offer is None or Game is None or commit_with_retry is None:
        raise SystemExit("DB apply is unavailable in this environment")
    totals = {"hidden_restored": 0, "offers_upserted": 0, "chunks": 0, "errors": []}
    db = SessionLocal()
    try:
        db_updates = [u for row in rows for u in row.get("updates", [])]
        for i in range(0, len(db_updates), chunk_size):
            chunk = db_updates[i : i + chunk_size]
            for update in chunk:
                try:
                    if update.get("type") == "restore_hidden":
                        offer = db.query(Offer).filter(Offer.id == int(update["offer_id"])).first()
                        if offer and str(offer.shop_name) not in FORBIDDEN_SHOPS:
                            offer.in_stock = True
                            totals["hidden_restored"] += 1
                    elif update.get("type") == "upsert_found":
                        game = db.query(Game).filter(Game.id == int(update["game_id"])).first()
                        if not game:
                            continue
                        for offer in update.get("offers") or []:
                            shop = offer.get("shop_name")
                            if shop in FORBIDDEN_SHOPS:
                                continue
                            url = offer.get("product_url") or offer.get("affiliate_url")
                            price = offer.get("price_pln")
                            if not shop or not url or price is None:
                                continue
                            verdict = _classify_found_offer(game, offer)
                            if not verdict["valid"]:
                                totals["errors"].append(
                                    f"rejected {shop} for {game.title}: {verdict['reason']}"
                                )
                                continue
                            upsert_keyshop_offer(
                                db,
                                game,
                                str(shop),
                                str(url),
                                float(price),
                                is_official=bool(offer.get("is_official")),
                            )
                            totals["offers_upserted"] += 1
                except Exception as exc:
                    totals["errors"].append(str(exc)[:180])
            commit_with_retry(db)
            totals["chunks"] += 1
    finally:
        db.close()
    totals["errors"] = totals["errors"][:20]
    return totals


def _state_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for state in (row.get("states") or {}).values():
            key = str(state.get("state") or "unknown")
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit/restore offer coverage from SP server")
    parser.add_argument("--mode", choices=("db", "api"), default="db")
    parser.add_argument("--tier", choices=("top5000", "queue", "all"), default="top5000")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--skip", type=int, default=0)
    parser.add_argument("--offset", type=int, default=None)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--shop", action="append", default=[])
    parser.add_argument("--shops", default=",".join(ALL_AUDIT_SHOPS))
    parser.add_argument("--apply", action="store_true", help="upload found offers")
    parser.add_argument("--show", type=int, default=80, help="result lines to print")
    parser.add_argument("--examples", type=int, default=50, help="classification examples to print")
    parser.add_argument("--upload-chunk-size", type=int, default=50)
    args = parser.parse_args()

    if args.offset is not None:
        args.skip = args.offset
    shops_raw = ",".join(args.shop) if args.shop else args.shops
    shops = _parse_shops(shops_raw)
    if args.mode == "api" and not _access_code():
        raise SystemExit("PANEL3_ACCESS_CODE is missing in env or tools/scan_config.env")

    if args.mode == "db":
        games = _db_games(tier=args.tier, limit=args.limit, skip=args.skip)
    else:
        tier = None if args.tier == "queue" else args.tier
        games = _queue(tier=tier, limit=args.limit + max(0, args.skip))
        if args.skip:
            games = games[args.skip :]
        games = games[: args.limit]
    if not games:
        print("No games in queue.")
        return 0

    print(
        f"Coverage audit: mode={args.mode} games={len(games)} tier={args.tier} "
        f"shops={','.join(shops)} apply={args.apply}"
    )

    stats = ShopScanStats()
    rows: list[dict[str, Any]] = []
    workers = max(1, min(args.parallel, len(games)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        if args.mode == "db":
            futures = {
                pool.submit(_db_scan_one, idx, len(games), game, shops, stats): idx
                for idx, game in enumerate(games, 1)
            }
        else:
            lookup_only = tuple(shop for shop in shops if shop in LOOKUP_SHOPS)
            futures = {
                pool.submit(_scan_one, idx, len(games), game, lookup_only, stats): idx
                for idx, game in enumerate(games, 1)
            }
        for future in as_completed(futures):
            row = future.result()
            rows.append(row)
            if len(rows) <= args.show:
                print(row["line"])

    updates = [
        {"game_id": row["game_id"], "offers": row["offers"]}
        for row in rows
        if row.get("game_id") and row.get("offers")
    ]
    offers_found = sum(len(row.get("offers") or []) for row in rows)
    db_updates = [u for row in rows for u in row.get("updates", [])]
    examples = [ex for row in rows for ex in row.get("examples", [])][: max(0, args.examples)]
    print(
        json.dumps(
            {
                "games_checked": len(rows),
                "games_with_hits": len(updates) if args.mode == "api" else sum(1 for row in rows if row.get("updates")),
                "offers_found": offers_found,
                "db_updates": len(db_updates),
                "state_counts": _state_counts(rows),
                "examples": examples,
                "shop_stats": stats.to_dict(),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    if args.apply and args.mode == "db" and db_updates:
        applied = _apply_db(rows, chunk_size=max(1, args.upload_chunk_size))
        print(json.dumps({"applied": applied}, ensure_ascii=False, indent=2))
    elif args.apply and updates:
        uploaded = _upload(updates, chunk_size=max(1, args.upload_chunk_size))
        print(json.dumps({"uploaded": uploaded}, ensure_ascii=False, indent=2))
    elif updates or db_updates:
        print("Dry-run only. Re-run with --apply to upload these offers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
