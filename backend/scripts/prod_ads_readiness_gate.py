"""Production ads-readiness gate.

Fails (exit 1) if matching/F2P/history fixes are missing from code, DB, or live pages.
Run on the VPS after every deploy:

  cd /opt/kupujpl-games && PYTHONPATH=. python scripts/prod_ads_readiness_gate.py

Optional:
  --base-url https://kupujpl.pl
  --skip-http   (DB + code markers only)
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MARKERS = {
    "app/parsers/keyshop_common.py": (
        "_is_store_sku_token",
        "detect_activation_region",
        "Both sides have distinctive product tokens",
        "_TITLE_MATCH_SHOPS",
    ),
    "app/core/game_offer_selection.py": ("Permanent Free-to-Play",),
    "app/core/worth_buy.py": ("DARMOWA GRA",),
    "app/core/price_history.py": ("Permanent F2P base games must not accumulate",),
    "app/core/canonical_price.py": ("game_price_context",),
}

FOCUS = {
    "counter-strike-2-730": {"must_free": True},
    "team-fortress-2-440": {"must_free": True},
    "resonance-a-plague-tale-legacy-2713000": {"must_free": False, "forbid_url": "innocence"},
}

ID_BACKED = {"Steam", "Steam US", "PlayStation Store", "Xbox Store"}
UA = "Mozilla/5.0 (compatible; KupujPL-AdsGate/1.0; +https://kupujpl.pl/games/)"


def _fail(msg: str, errors: list[str]) -> None:
    errors.append(msg)
    print(f"FAIL: {msg}")


def _ok(msg: str) -> None:
    print(f"OK: {msg}")


def check_code_markers(errors: list[str]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for rel, needles in MARKERS.items():
        path = ROOT / rel
        if not path.is_file():
            _fail(f"missing file {rel}", errors)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        digests[rel] = hashlib.md5(text.encode("utf-8")).hexdigest()
        for needle in needles:
            if needle not in text:
                _fail(f"{rel} missing marker: {needle!r}", errors)
        _ok(f"{rel} markers present md5={digests[rel][:12]}")
    return digests


def check_imports(errors: list[str]) -> None:
    try:
        from app.parsers.keyshop_common import (  # noqa: WPS433
            classify_keyshop_product,
            detect_activation_region,
            title_mismatch,
            upsert_keyshop_offer,
        )
        from app.core.worth_buy import compute_worth_buy  # noqa: WPS433
        from app.core.canonical_price import game_price_context  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        _fail(f"import error: {exc}", errors)
        return

    if not title_mismatch("Resonance: A Plague Tale Legacy", "A Plague Tale: Innocence"):
        _fail("title_mismatch does not reject Innocence vs Legacy", errors)
    else:
        _ok("title_mismatch rejects Innocence vs Legacy")

    verdict = classify_keyshop_product(
        "Resonance: A Plague Tale Legacy",
        "A Plague Tale: Innocence",
        "https://www.gog.com/pl/game/a_plague_tale_innocence",
    )
    if verdict.get("valid"):
        _fail(f"classify accepts Innocence for Legacy: {verdict}", errors)
    else:
        _ok(f"classify rejects Innocence reason={verdict.get('reason')}")

    free = compute_worth_buy(current_price=131.88, is_free=True)
    if not free or free.label != "DARMOWA GRA":
        _fail(f"worth_buy F2P label wrong: {free}", errors)
    else:
        _ok("worth_buy F2P => DARMOWA GRA")

    _ = detect_activation_region, upsert_keyshop_offer, game_price_context
    _ok("critical imports OK")


def check_db(errors: list[str]) -> None:
    from app.core.database import SessionLocal  # noqa: WPS433
    from app.core.canonical_price import get_current_min_price, game_price_context  # noqa: WPS433
    from app.models.models import Game, Offer  # noqa: WPS433

    db = SessionLocal()
    try:
        paid_f2p = (
            db.query(Offer)
            .join(Game)
            .filter(
                Game.is_free.is_(True),
                Offer.in_stock.is_(True),
                Offer.price_pln > 0.01,
                ~Offer.shop_name.in_(list(ID_BACKED)),
            )
            .count()
        )
        if paid_f2p:
            _fail(f"f2p_paid_instock_keyshops={paid_f2p}", errors)
        else:
            _ok("f2p_paid_instock_keyshops=0")

        for slug, rules in FOCUS.items():
            game = db.query(Game).filter(Game.slug == slug).first()
            if not game:
                _fail(f"missing game {slug}", errors)
                continue
            ctx = game_price_context(db, game)
            price, _offer = get_current_min_price(db, game)
            if rules["must_free"]:
                if not game.is_free:
                    _fail(f"{slug} is_free=False", errors)
                if price not in (0, 0.0) and price is not None:
                    _fail(f"{slug} canonical price={price}", errors)
                if ctx.price_pln != 0.0 or not ctx.is_free:
                    _fail(f"{slug} game_price_context={ctx}", errors)
                offs = (
                    db.query(Offer)
                    .filter(Offer.game_id == game.id, Offer.in_stock.is_(True), Offer.price_pln > 0.01)
                    .filter(~Offer.shop_name.in_(list(ID_BACKED)))
                    .count()
                )
                if offs:
                    _fail(f"{slug} still has {offs} paid keyshop in_stock", errors)
                else:
                    _ok(f"{slug} F2P canonical=0 no paid keyshops")
            else:
                forbid = rules.get("forbid_url")
                if forbid:
                    bad = (
                        db.query(Offer)
                        .filter(
                            Offer.game_id == game.id,
                            Offer.in_stock.is_(True),
                            Offer.affiliate_url.ilike(f"%{forbid}%"),
                        )
                        .count()
                    )
                    if bad:
                        _fail(f"{slug} in_stock offer URL contains {forbid!r}", errors)
                    else:
                        _ok(f"{slug} no in_stock URL with {forbid!r}")
    finally:
        db.close()


def _http_get(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return int(resp.status), resp.read().decode("utf-8", "replace")


def check_http(base_url: str, errors: list[str]) -> None:
    import json

    base = base_url.rstrip("/")
    # CS2 HTML
    status, html = _http_get(f"{base}/games/gra/counter-strike-2-730")
    if status != 200:
        _fail(f"CS2 HTML HTTP {status}", errors)
    else:
        if "DARMOWA GRA" not in html and "Free-to-Play" not in html:
            _fail("CS2 HTML missing DARMOWA/Free-to-Play", errors)
        if "KUP TERAZ" in html:
            _fail("CS2 HTML still shows KUP TERAZ", errors)
        if "0,00" not in html and "0.00" not in html:
            _fail("CS2 HTML missing 0 price", errors)
        else:
            _ok("CS2 HTML F2P signals OK")

    # APIs
    for slug, rules in FOCUS.items():
        status, body = _http_get(f"{base}/games/api/games/{slug}")
        if status != 200:
            _fail(f"API {slug} HTTP {status}", errors)
            continue
        data = json.loads(body)
        if rules["must_free"]:
            if not data.get("is_free"):
                _fail(f"API {slug} is_free={data.get('is_free')}", errors)
            best = data.get("best_price_pln")
            if best not in (0, 0.0):
                _fail(f"API {slug} best_price_pln={best}", errors)
            shops = [o.get("shop_name") for o in data.get("offers") or []]
            paid = [
                o
                for o in (data.get("offers") or [])
                if (o.get("shop_name") not in ID_BACKED) and (o.get("price_pln") or 0) > 0.01
            ]
            if paid:
                _fail(f"API {slug} paid offers {paid}", errors)
            else:
                _ok(f"API {slug} free best={best} shops={shops}")
        else:
            forbid = rules.get("forbid_url")
            if forbid and any(forbid in ((o.get("affiliate_url") or "").lower()) for o in data.get("offers") or []):
                _fail(f"API {slug} offer URL contains {forbid}", errors)
            else:
                _ok(f"API {slug} clean of {forbid}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="https://kupujpl.pl")
    parser.add_argument("--skip-http", action="store_true")
    args = parser.parse_args()

    errors: list[str] = []
    print("=== ads readiness gate ===")
    check_code_markers(errors)
    check_imports(errors)
    check_db(errors)
    if not args.skip_http:
        try:
            check_http(args.base_url, errors)
        except urllib.error.HTTPError as exc:
            _fail(f"HTTP error: {exc}", errors)
        except Exception as exc:  # noqa: BLE001
            _fail(f"HTTP check failed: {exc}", errors)

    if errors:
        print(f"\nGATE FAILED ({len(errors)} issues)")
        return 1
    print("\nGATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
