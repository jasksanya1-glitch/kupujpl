"""Document SSR status by User-Agent: browsers/Googlebot 200; bare curl may 403."""
from __future__ import annotations

import os

import pytest
import requests

PROD = os.environ.get("GAMES_BASE_URL", "https://kupujpl.pl/games").rstrip("/")

PATHS = [
    "/gra/hades-ii",
    "/gra/warhammer-40000-rogue-trader-2186680",
    "/gra/guacamelee-super-turbo-championship-edition-275390",
    "/gra/warhammer-40000-space-marine-2-2183900",
    "/promocje",
]

BROWSER = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
GOOGLEBOT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"


@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("ua", [BROWSER, GOOGLEBOT], ids=["browser", "googlebot"])
def test_ssr_pages_ok_for_browser_and_googlebot(path: str, ua: str) -> None:
    if os.environ.get("SKIP_LIVE_HTTP") == "1":
        pytest.skip("SKIP_LIVE_HTTP=1")
    r = requests.get(
        f"{PROD}{path}",
        headers={"User-Agent": ua},
        timeout=25,
        allow_redirects=True,
    )
    assert r.status_code == 200, f"{path} ua={ua[:32]} → {r.status_code}"
    assert len(r.content) > 500


@pytest.mark.parametrize("path", PATHS[:2])
def test_bare_curl_ua_may_be_blocked_not_500(path: str) -> None:
    """Independent scanners using curl/UA often see 403 — must not be reported as HTTP 500."""
    if os.environ.get("SKIP_LIVE_HTTP") == "1":
        pytest.skip("SKIP_LIVE_HTTP=1")
    r = requests.get(
        f"{PROD}{path}",
        headers={"User-Agent": "curl/8.0.0"},
        timeout=25,
        allow_redirects=True,
    )
    assert r.status_code != 500
    assert r.status_code in {200, 403, 429}
