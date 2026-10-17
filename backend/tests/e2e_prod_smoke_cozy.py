"""Read-only Playwright smoke against production (no auth writes / no purchases)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://kupujpl.pl/games"
SHOT_DIR = Path(__file__).resolve().parents[2] / "docs" / "stabilization-shots-20261017"
VIEWPORTS = [
    (360, 800),
    (390, 844),
    (430, 932),
    (768, 1024),
    (1440, 900),
    (1920, 1080),
]


def main() -> int:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for w, h in VIEWPORTS:
            context = browser.new_context(
                viewport={"width": w, "height": h},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()
            console_errors: list[str] = []
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text)
                if msg.type == "error"
                else None,
            )
            failed_reqs: list[str] = []
            page.on(
                "requestfailed",
                lambda req: failed_reqs.append(f"{req.url} :: {req.failure}"),
            )

            page.goto(f"{BASE}/", wait_until="domcontentloaded", timeout=60000)
            html = page.content()
            if "theme-cozy-orange" not in html:
                errors.append(f"{w}x{h}: missing cozy theme class")
            if "quenly-logo" not in html and "brand-logo" not in html:
                errors.append(f"{w}x{h}: missing Quenly logo marker")
            canon = page.locator('link[rel="canonical"]').get_attribute("href") or ""
            if canon != f"{BASE}/":
                errors.append(f"{w}x{h}: bad home canonical {canon}")

            # search (prefer visible cozy hero input; header search is often hidden on mobile)
            box = page.locator("#cozy-search-input")
            if box.count() == 0 or not box.first.is_visible():
                box = page.locator("#search-input:visible, input[type=search]:visible")
            if box.count() and box.first.is_visible():
                box.first.fill("Hades II", timeout=5000)
                page.keyboard.press("Enter")
                page.wait_for_timeout(1200)

            page.goto(f"{BASE}/gra/hades-ii", wait_until="domcontentloaded", timeout=60000)
            ghtml = page.content()
            if "117" not in ghtml:
                errors.append(f"{w}x{h}: Hades price missing on SSR/page")
            if "/api/go/" not in ghtml:
                errors.append(f"{w}x{h}: missing affiliate go links")
            gcanon = page.locator('link[rel="canonical"]').get_attribute("href") or ""
            if not gcanon.startswith(f"{BASE}/gra/hades-ii"):
                errors.append(f"{w}x{h}: bad game canonical {gcanon}")

            # overflow check
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
            )
            if overflow:
                errors.append(f"{w}x{h}: horizontal overflow")

            page.screenshot(path=str(SHOT_DIR / f"home-{w}x{h}.png"), full_page=False)
            # legal read-only
            if w == 1440:
                for path in ("/o-nas", "/regulamin", "/kontakt"):
                    resp = page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=45000)
                    if not resp or resp.status >= 400:
                        errors.append(f"legal {path} status={getattr(resp, 'status', None)}")

            crit_failed = [
                u
                for u in failed_reqs
                if not re.search(
                    r"favicon|umami|analytics|chrome-extension|doubleclick|site-chat|ERR_ABORTED",
                    u,
                    re.I,
                )
            ]
            crit_failed = [u for u in crit_failed if "/static/" in u or "/api/" in u]
            if crit_failed:
                errors.append(f"{w}x{h}: failed requests: {crit_failed[:5]}")

            context.close()
        browser.close()

    print("SHOT_DIR", SHOT_DIR)
    if errors:
        print("FAIL")
        for e in errors:
            print(" -", e)
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
