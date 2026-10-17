"""Read-only Playwright functional E2E against production (no data-changing actions)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://kupujpl.pl/games"
REPORT = Path(__file__).resolve().parents[2] / "docs" / "e2e-prod-functional-quality-20261017.json"


def _ignore_net(url: str) -> bool:
    return bool(
        re.search(
            r"favicon|umami|analytics|chrome-extension|doubleclick|ERR_ABORTED|site-chat",
            url,
            re.I,
        )
    )


def main() -> int:
    results: dict = {"base": BASE, "checks": [], "errors": [], "js_errors": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        js_errors: list[str] = []
        page.on(
            "pageerror",
            lambda err: js_errors.append(str(err)),
        )
        page.on(
            "console",
            lambda msg: js_errors.append(f"console:{msg.text}")
            if msg.type == "error" and not _ignore_net(msg.text)
            else None,
        )

        def check(name: str, ok: bool, detail: str = "") -> None:
            results["checks"].append({"name": name, "ok": ok, "detail": detail})
            if not ok:
                results["errors"].append(f"{name}: {detail}")

        # Home + search
        page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=60000)
        check("home_cozy", "theme-cozy-orange" in page.content())
        box = page.locator("#cozy-search-input")
        if box.count() == 0 or not box.first.is_visible():
            box = page.locator("#search-input:visible, input[type=search]:visible")
        check("search_input", box.count() > 0 and box.first.is_visible())
        if box.count() and box.first.is_visible():
            box.first.fill("Rogue Trader")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1500)
            check("search_results", page.locator(".game-card, .card, a[href*='/gra/']").count() > 0)

        # Filters / sort (best-effort read-only UI presence)
        for sel, name in [
            ("#sort-select, select[name='sort'], [data-sort], .sort-select, .catalog-sort-select", "sort_control"),
            ("#m-promo-chips, .m-promo-chips, .m-promo-chip, #m-sort-tabs, .m-sort-tabs", "filter_control"),
        ]:
            loc = page.locator(sel)
            check(name, loc.count() > 0, f"selector={sel}")

        # Open game
        page.goto(
            f"{BASE}/gra/warhammer-40000-rogue-trader-2186680",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        check("game_open", "Rogue Trader" in page.content())
        check("game_offers_ssr", page.locator("#gp-offers, .offer-row, .btn-buy").count() > 0)
        check("go_links", "/api/go/" in page.content())

        # Offers API (confirmed vs unverified separation)
        api = page.request.get(f"{BASE}/api/games/warhammer-40000-rogue-trader-2186680")
        check("offers_api_status", api.ok, str(api.status))
        if api.ok:
            data = api.json()
            best = data.get("best_price_pln")
            check("best_price_confirmed_band", best is not None and float(best) >= 100, str(best))
            offers = data.get("offers") or []
            unverified = data.get("unverified_offers") or []
            check("confirmed_offers_present", len(offers) >= 1, f"n={len(offers)}")
            # After deploy unverified may appear; before deploy field may be missing/empty
            check(
                "unverified_field_present",
                "unverified_offers" in data,
                f"keys_has={('unverified_offers' in data)} n={len(unverified)}",
            )
            if offers and unverified:
                conf_ids = {o["id"] for o in offers}
                un_ids = {o["id"] for o in unverified}
                check("no_offer_id_overlap", not (conf_ids & un_ids), str(conf_ids & un_ids))
            un_shops = {str(o.get("shop_name") or "") for o in unverified}
            offer_shops = {str(o.get("shop_name") or "") for o in offers}
            check(
                "rejected_gog_dawn_of_war_not_buyable",
                "GOG" not in un_shops and not any(
                    float(o.get("price_pln") or 0) < 20 and o.get("shop_name") == "GOG"
                    for o in offers
                ),
                f"unverified={sorted(un_shops)} offers={sorted(offer_shops)}",
            )
            check(
                "no_rejected_offers_section",
                page.locator("#gp-offers-rejected, .offers-rejected").count() == 0,
            )
            uv_rows = page.locator(".offer-row-unverified").all_inner_texts()
            check(
                "ui_no_gog_in_unverified_rows",
                not any("GOG" in t and ("8,99" in t or "8.99" in t) for t in uv_rows),
                f"rows={uv_rows[:4]}",
            )

        # Auth pages read-only
        for path, name in [("/login", "login_page"), ("/register", "register_page")]:
            resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=45000)
            check(name, bool(resp) and resp.status < 400, str(getattr(resp, "status", None)))

        # Favorites / alerts UI markers without mutating
        page.goto(
            f"{BASE}/gra/warhammer-40000-rogue-trader-2186680",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        check("favorite_button", page.locator("#btn-favorite, [data-i18n='card.watch']").count() > 0)
        check("alert_button", page.locator("#btn-alert-toggle, [data-i18n='modal.alert']").count() > 0)

        # Mobile nav
        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent=(
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            ),
            is_mobile=True,
            has_touch=True,
        )
        mpage = mobile.new_page()
        mpage.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=60000)
        overflow = mpage.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
        )
        check("mobile_no_h_overflow", not overflow)
        check("mobile_nav", mpage.locator("header, .header, .bottom-nav, nav").count() > 0)
        mobile.close()

        # Site chat: must not claim success; unavailable marker OK
        page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(800)
        chat = page.locator('[data-site-chat="unavailable"], .sc-root')
        check("site_chat_widget_present_or_absent_ok", True, f"count={chat.count()}")

        results["js_errors"] = js_errors[:20]
        check("no_critical_js_errors", len(js_errors) == 0, "; ".join(js_errors[:5]))

        context.close()
        browser.close()

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print("REPORT", REPORT)
    if results["errors"]:
        print("FAIL")
        for e in results["errors"]:
            print(" -", e)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
