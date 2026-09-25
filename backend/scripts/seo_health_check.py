#!/usr/bin/env python3
"""Lightweight public SEO health check for kupujpl.pl/games/.

Examples:
  python scripts/seo_health_check.py --sample-size 50
  python scripts/seo_health_check.py --full --concurrency 4
"""
from __future__ import annotations

import argparse
import random
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = "KupujPL-SEOHealthCheck/1.0 (+https://kupujpl.pl/games/)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
GOOGLEBOT_UA = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
DEFAULT_ORIGIN = "https://kupujpl.pl"
DEFAULT_BASE = "https://kupujpl.pl/games"

CANONICAL_RE = re.compile(
    r'<link[^>]+rel=["\']canonical["\'][^>]*href=["\']([^"\']+)["\']',
    re.I,
)
CANONICAL_RE_ALT = re.compile(
    r'<link[^>]+href=["\']([^"\']+)["\'][^>]*rel=["\']canonical["\']',
    re.I,
)
META_ROBOTS_RE = re.compile(
    r'<meta[^>]+name=["\']robots["\'][^>]*content=["\']([^"\']+)["\']',
    re.I,
)
H1_RE = re.compile(r"<h1\b", re.I)


@dataclass
class FetchResult:
    url: str
    status: int | None = None
    final_url: str | None = None
    redirects: int = 0
    location: str | None = None
    body: str = ""
    error: str | None = None
    x_robots: str | None = None


@dataclass
class Report:
    critical: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def fetch(
    url: str,
    *,
    ua: str = USER_AGENT,
    timeout: float = 20.0,
    method: str = "GET",
    max_redirects: int = 5,
) -> FetchResult:
    """Fetch URL following redirects so hop count is visible."""
    current = url
    redirects = 0
    last_location: str | None = None
    for _ in range(max_redirects + 1):
        req = Request(
            current,
            method=method,
            headers={
                "User-Agent": ua,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pl,en;q=0.8",
            },
        )
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = ""
                if method == "GET":
                    raw = resp.read(2_000_000)
                    body = raw.decode("utf-8", errors="replace")
                return FetchResult(
                    url=url,
                    status=getattr(resp, "status", None) or resp.getcode(),
                    final_url=resp.geturl(),
                    redirects=redirects,
                    location=last_location,
                    body=body,
                    x_robots=resp.headers.get("X-Robots-Tag"),
                )
        except HTTPError as exc:
            status = exc.code
            loc = exc.headers.get("Location") if exc.headers else None
            if status in (301, 302, 303, 307, 308) and loc:
                redirects += 1
                last_location = loc
                current = urljoin(current, loc)
                continue
            body = ""
            try:
                body = exc.read(200_000).decode("utf-8", errors="replace")
            except Exception:
                pass
            return FetchResult(
                url=url,
                status=status,
                final_url=current,
                redirects=redirects,
                location=loc,
                body=body,
                error=str(exc),
                x_robots=exc.headers.get("X-Robots-Tag") if exc.headers else None,
            )
        except URLError as exc:
            return FetchResult(url=url, error=str(exc.reason if hasattr(exc, "reason") else exc))
        except Exception as exc:  # noqa: BLE001
            return FetchResult(url=url, error=str(exc))
    return FetchResult(
        url=url,
        status=None,
        final_url=current,
        redirects=redirects,
        location=last_location,
        error="too many redirects",
    )


def first_hop(url: str, *, ua: str, timeout: float = 20.0) -> FetchResult:
    """Return the first HTTP response without following redirects."""
    opener = urllib.request.build_opener(_NoRedirect)
    req = Request(
        url,
        method="GET",
        headers={
            "User-Agent": ua,
            "Accept": "text/html,*/*;q=0.8",
            "Accept-Language": "pl,en;q=0.8",
        },
    )
    try:
        with opener.open(req, timeout=timeout) as resp:
            return FetchResult(
                url=url,
                status=getattr(resp, "status", None) or resp.getcode(),
                final_url=resp.geturl(),
                redirects=0,
                location=resp.headers.get("Location"),
                x_robots=resp.headers.get("X-Robots-Tag"),
            )
    except HTTPError as exc:
        return FetchResult(
            url=url,
            status=exc.code,
            final_url=url,
            redirects=0,
            location=exc.headers.get("Location") if exc.headers else None,
            x_robots=exc.headers.get("X-Robots-Tag") if exc.headers else None,
            error=None if exc.code in (301, 302, 303, 307, 308) else str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return FetchResult(url=url, error=str(exc))


def parse_canonical(html: str) -> str | None:
    m = CANONICAL_RE.search(html) or CANONICAL_RE_ALT.search(html)
    return m.group(1).strip() if m else None


def parse_meta_robots(html: str) -> str | None:
    m = META_ROBOTS_RE.search(html)
    return m.group(1).strip() if m else None


def count_h1(html: str) -> int:
    return len(H1_RE.findall(html))


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def parse_sitemap_locs(xml_text: str) -> tuple[str, list[str]]:
    """Return ('index'|'urlset', list of loc URLs)."""
    root = ET.fromstring(xml_text)
    tag = _local_tag(root.tag).lower()
    locs: list[str] = []
    for el in root.iter():
        if _local_tag(el.tag).lower() == "loc" and el.text:
            locs.append(el.text.strip())
    kind = "index" if tag == "sitemapindex" else "urlset"
    return kind, locs


def classify_url(url: str, base: str) -> str:
    path = urlparse(url).path
    base_path = urlparse(base).path.rstrip("/") or "/games"
    rel = path[len(base_path) :] if path.startswith(base_path) else path
    rel = rel or "/"
    if rel in ("/", ""):
        return "home"
    if rel.startswith("/gra/"):
        return "game"
    if rel.startswith("/kategoria/"):
        return "category"
    if rel.startswith("/blog"):
        return "blog"
    if "promocje" in rel or "okazje" in rel or "gry-pc" in rel or "darmowe" in rel:
        return "deal"
    return "other"


def check_www_redirect(report: Report, origin: str) -> None:
    www_origin = origin.replace("://", "://www.", 1) if "://www." not in origin else origin
    checks = (
        ("www /games/", f"{www_origin}/games/", f"{origin}/games/"),
        ("www /games/?q=witcher", f"{www_origin}/games/?q=witcher", f"{origin}/games/?q=witcher"),
        ("http www /games/", f"http://www.kupujpl.pl/games/", f"{origin}/games/"),
        ("http apex /games/", f"http://kupujpl.pl/games/", f"{origin}/games/"),
    )
    apex_host = urlparse(origin).netloc
    for label, url, expect in checks:
        first = first_hop(url, ua=BROWSER_UA)
        report.info.append(
            f"www redirect {label}: status={first.status} location={first.location}"
        )
        if first.error and first.status is None:
            report.critical.append(f"{label}: {first.error}")
            continue
        if first.status != 301:
            report.critical.append(f"{label}: expected 301, got {first.status}")
            continue
        loc = first.location or ""
        absolute = urljoin(url, loc)
        got = urlparse(absolute)
        want = urlparse(expect)
        if got.scheme != "https" or got.netloc != apex_host:
            report.critical.append(f"{label}: Location not apex https: {loc}")
        if got.path != want.path:
            report.critical.append(f"{label}: path mismatch: {loc} (want {expect})")
        if want.query and got.query != want.query:
            report.critical.append(f"{label}: query not preserved: {loc}")

        followed = fetch(url, ua=BROWSER_UA, max_redirects=5)
        if followed.redirects > 1:
            report.critical.append(
                f"{label}: redirect chain too long ({followed.redirects} hops) -> {followed.final_url}"
            )


def check_bots(report: Report, base: str, origin: str) -> None:
    paths = [
        f"{origin}/robots.txt",
        f"{base}/",
        f"{base}/sitemap.xml",
    ]
    agents = {
        "browser": BROWSER_UA,
        "googlebot": GOOGLEBOT_UA,
        "bingbot": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        "healthcheck": USER_AGENT,
    }
    for name, ua in agents.items():
        for path in paths:
            r = fetch(path, ua=ua)
            report.info.append(f"bot[{name}] {path} -> {r.status}")
            if name == "googlebot" and r.status == 403:
                report.critical.append(f"Googlebot got 403 for {path}")
            if name in ("browser", "googlebot", "bingbot") and r.status != 200:
                report.warnings.append(f"{name} {path} -> {r.status}")


def check_home_h1(report: Report, base: str) -> None:
    r = fetch(f"{base}/", ua=BROWSER_UA)
    if r.status != 200:
        report.critical.append(f"home status {r.status}")
        return
    n = count_h1(r.body)
    report.info.append(f"home H1 count={n}")
    if n != 1:
        report.critical.append(f"home must have exactly 1 H1, found {n}")
    can = parse_canonical(r.body)
    if can and can.rstrip("/") != base.rstrip("/"):
        report.warnings.append(f"home canonical unexpected: {can}")
    robots = parse_meta_robots(r.body)
    if robots and "noindex" in robots.lower():
        report.critical.append(f"home meta robots noindex: {robots}")
    if r.x_robots and "noindex" in r.x_robots.lower():
        report.critical.append(f"home X-Robots-Tag noindex: {r.x_robots}")


def load_sitemaps(report: Report, base: str, timeout: float) -> list[str]:
    index_url = f"{base}/sitemap.xml"
    r = fetch(index_url, ua=BROWSER_UA, timeout=timeout)
    if r.status != 200:
        report.critical.append(f"sitemap index HTTP {r.status}")
        return []
    kind, locs = parse_sitemap_locs(r.body)
    report.info.append(f"sitemap index kind={kind} children={len(locs)}")
    all_urls: list[str] = []
    if kind == "urlset":
        all_urls.extend(locs)
        return all_urls

    for child in locs:
        cr = fetch(child, ua=BROWSER_UA, timeout=timeout)
        if cr.status != 200:
            report.critical.append(f"child sitemap {child} -> {cr.status}")
            continue
        _ckind, clocs = parse_sitemap_locs(cr.body)
        report.info.append(f"  {child}: urls={len(clocs)}")
        if len(clocs) >= 50_000:
            report.critical.append(f"{child} has {len(clocs)} URLs (>= 50000)")
        bad_www = sum(1 for u in clocs if "www.kupujpl" in u)
        bad_http = sum(1 for u in clocs if u.startswith("http://"))
        if bad_www:
            report.critical.append(f"{child}: {bad_www} www URLs")
        if bad_http:
            report.critical.append(f"{child}: {bad_http} http URLs")
        all_urls.extend(clocs)

    counts: dict[str, int] = {}
    for u in all_urls:
        t = classify_url(u, base)
        counts[t] = counts.get(t, 0) + 1
    report.info.append("URL types: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return all_urls


def sample_pages(
    report: Report,
    urls: list[str],
    *,
    sample_size: int,
    full: bool,
    concurrency: int,
    timeout: float,
    base: str,
) -> None:
    if not urls:
        return
    if full:
        chosen = list(urls)
    else:
        by_type: dict[str, list[str]] = {}
        for u in urls:
            by_type.setdefault(classify_url(u, base), []).append(u)
        chosen: list[str] = []
        for u in urls:
            if classify_url(u, base) == "home":
                chosen.append(u)
                break
        remaining = max(0, sample_size - len(chosen))
        types = [t for t in by_type if t != "home"]
        per = max(1, remaining // max(1, len(types))) if types else 0
        for t in types:
            pool = by_type[t]
            n = min(per, len(pool))
            pick = pool[:n] if len(pool) <= n else random.sample(pool, n)
            chosen.extend(pick)
        if len(chosen) > sample_size:
            chosen = chosen[:sample_size]
        elif len(chosen) < sample_size:
            extra = [u for u in urls if u not in chosen]
            need = sample_size - len(chosen)
            if extra:
                chosen.extend(extra[:need] if len(extra) <= need else random.sample(extra, need))

    report.info.append(f"checking {len(chosen)} page(s) (full={full})")

    def _one(u: str) -> tuple[str, FetchResult, str | None, str | None, int]:
        res = fetch(u, ua=BROWSER_UA, timeout=timeout)
        can = parse_canonical(res.body) if res.body else None
        robots = parse_meta_robots(res.body) if res.body else None
        h1 = count_h1(res.body) if res.body else 0
        return u, res, can, robots, h1

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futs = [pool.submit(_one, u) for u in chosen]
        for fut in as_completed(futs):
            u, res, can, robots, h1 = fut.result()
            if res.error and res.status is None:
                report.warnings.append(f"{u}: fetch error {res.error}")
                continue
            if res.status != 200:
                report.warnings.append(f"{u}: HTTP {res.status}")
                continue
            if res.redirects:
                report.warnings.append(f"{u}: followed {res.redirects} redirects -> {res.final_url}")
            if can:
                parsed = urlparse(can)
                if parsed.scheme != "https":
                    report.critical.append(f"{u}: canonical not https: {can}")
                if parsed.netloc.startswith("www."):
                    report.critical.append(f"{u}: canonical on www: {can}")
            else:
                report.warnings.append(f"{u}: missing canonical")
            if robots and "noindex" in robots.lower():
                report.critical.append(f"{u}: meta robots noindex but in sitemap: {robots}")
            if res.x_robots and "noindex" in res.x_robots.lower():
                report.critical.append(f"{u}: X-Robots-Tag noindex: {res.x_robots}")
            if classify_url(u, base) == "home" and h1 != 1:
                report.critical.append(f"{u}: H1 count={h1}")


def check_robots(report: Report, origin: str, base: str) -> None:
    r = fetch(f"{origin}/robots.txt", ua=BROWSER_UA)
    if r.status != 200:
        report.critical.append(f"robots.txt HTTP {r.status}")
        return
    text = r.body
    report.info.append("robots.txt loaded")
    if "Sitemap:" not in text:
        report.critical.append("robots.txt missing Sitemap directive")
    elif f"{base}/sitemap.xml" not in text:
        report.warnings.append(f"robots Sitemap may not point to {base}/sitemap.xml")
    for bad in ("Disallow: /games/static", "Disallow: /static"):
        if bad in text:
            report.warnings.append(f"robots disallows assets: {bad}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="KupujPL Games SEO health check")
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--base", default=DEFAULT_BASE, help="Games base URL without trailing slash")
    parser.add_argument("--sample-size", type=int, default=50)
    parser.add_argument("--full", action="store_true", help="Check all sitemap URLs (slow)")
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)

    random.seed(args.seed)
    origin = args.origin.rstrip("/")
    base = args.base.rstrip("/")
    report = Report()

    print(f"SEO health check — origin={origin} base={base}")
    print("=" * 60)

    check_robots(report, origin, base)
    check_www_redirect(report, origin)
    check_bots(report, base, origin)
    check_home_h1(report, base)
    urls = load_sitemaps(report, base, args.timeout)
    sample_pages(
        report,
        urls,
        sample_size=args.sample_size,
        full=args.full,
        concurrency=args.concurrency,
        timeout=args.timeout,
        base=base,
    )

    print("\nINFO")
    for line in report.info:
        print(f"  - {line}")
    if report.warnings:
        print("\nWARNINGS")
        for line in report.warnings:
            print(f"  ! {line}")
    if report.critical:
        print("\nCRITICAL")
        for line in report.critical:
            print(f"  x {line}")
        print(f"\nFAILED — {len(report.critical)} critical issue(s)")
        return 1

    print("\nOK — no critical issues")
    return 0


if __name__ == "__main__":
    sys.exit(main())
