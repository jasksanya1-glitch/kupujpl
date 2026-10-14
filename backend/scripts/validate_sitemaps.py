#!/usr/bin/env python3
"""Sample sitemap URLs with rate limiting (READ-ONLY against production).

Usage:
  python -m scripts.validate_sitemaps
  python -m scripts.validate_sitemaps --base https://kupujpl.pl/games --sample 30
"""
from __future__ import annotations

import argparse
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
UA = "Mozilla/5.0 (compatible; KupujPLSitemapValidator/1.0; +https://kupujpl.pl/)"


def _iri_to_uri(url: str) -> str:
    """Encode non-ASCII path segments so urllib can fetch Polish slugs."""
    parts = urllib.parse.urlsplit(url)
    encoded_path = urllib.parse.quote(parts.path, safe="/:@")
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, encoded_path, parts.query, parts.fragment)
    )


def _fetch(url: str, timeout: float = 25) -> tuple[int, str, str]:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(
        _iri_to_uri(url), headers={"User-Agent": UA, "Cache-Control": "no-cache"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            body = r.read().decode("utf-8", "replace")
            ct = r.headers.get("Content-Type", "")
            return int(r.status), ct, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace") if e.fp else ""
        return int(e.code), "", body


def _locs(xml_text: str) -> list[str]:
    root = ET.fromstring(xml_text)
    return [el.text.strip() for el in root.findall(".//sm:loc", NS) if el.text]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default="https://kupujpl.pl/games")
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.15)
    args = ap.parse_args()
    base = args.base.rstrip("/")
    # robots.txt (origin root; browser-like UA — bare curl may be edge-blocked)
    robots_url = "https://kupujpl.pl/robots.txt"
    rst, rct, rbody = _fetch(robots_url)
    robots_ok = (
        rst == 200
        and "text/plain" in (rct or "").lower()
        and "User-agent" in rbody
        and "/games/" in rbody
    )
    print(f"robots.txt: {rst} ct={rct[:40]!r} ok={robots_ok}")
    if not robots_ok and rbody:
        print("  robots_snippet:", repr(rbody[:160]))

    maps = [
        f"{base}/sitemap.xml",
        f"{base}/sitemap-games.xml",
        f"{base}/sitemap-categories.xml",
        f"{base}/sitemap-deals.xml",
        f"{base}/sitemap-blog.xml",
    ]
    all_urls: list[str] = []
    for murl in maps:
        st, ct, body = _fetch(murl)
        ok = st == 200 and ("xml" in ct.lower() or body.lstrip().startswith("<"))
        print(f"sitemap {murl.split('/')[-1]}: {st} ct={ct[:40]!r} ok={ok}")
        if not ok:
            continue
        try:
            locs = _locs(body)
        except ET.ParseError as e:
            print("  XML parse error:", e)
            continue
        print(f"  urls={len(locs)}")
        all_urls.extend(locs)

    # Prefer leaf URLs (skip nested sitemap indexes already expanded)
    leaf = [u for u in all_urls if "sitemap" not in u.split("/")[-1]]
    # Deduplicate preserving order
    seen: set[str] = set()
    uniq: list[str] = []
    for u in leaf:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    sample = uniq[: args.sample]
    print(f"checking sample={len(sample)} of unique_leaf={len(uniq)}")

    stats = {"200": 0, "3xx": 0, "404": 0, "other": 0, "noindex": 0, "canon_mismatch": 0}

    def check(url: str) -> None:
        time.sleep(args.delay)
        st, _, body = _fetch(url)
        if st == 200:
            stats["200"] += 1
        elif 300 <= st < 400:
            stats["3xx"] += 1
        elif st == 404:
            stats["404"] += 1
        else:
            stats["other"] += 1
        if st == 200:
            if re.search(r'name=["\']robots["\'][^>]*noindex|content=["\'][^"\']*noindex', body, re.I):
                stats["noindex"] += 1
            m = re.search(r'rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', body, re.I)
            if not m:
                m = re.search(r'href=["\']([^"\']+)["\'][^>]*rel=["\']canonical["\']', body, re.I)
            if m and m.group(1).rstrip("/") != url.rstrip("/"):
                # Allow trailing-slash differences only
                if m.group(1).rstrip("/") + "/" != url.rstrip("/") + "/":
                    stats["canon_mismatch"] += 1
                    print("  canon_mismatch", url, "->", m.group(1))

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(check, u) for u in sample]
        for f in as_completed(futs):
            f.result()
    print("sample_stats", stats)
    return 0 if stats["404"] == 0 and stats["other"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
