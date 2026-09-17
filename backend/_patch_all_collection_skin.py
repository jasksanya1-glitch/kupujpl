#!/usr/bin/env python3
"""Skin deals/genre SEO landings + seo-card collection cards."""
from __future__ import annotations

import ast
from pathlib import Path

TARGET = Path("/opt/kupujpl-games/app/core/seo_pages.py")

NEW_COLLECTION_CARDS = r'''def _collection_cards(games: list[GameListResponse]) -> tuple[str, list[dict]]:
    cards = ""
    list_items: list[dict] = []
    for i, g in enumerate(games, start=1):
        sav = f" −{g.savings_pct}%" if g.savings_pct else ""
        price = f"{g.best_price_pln:.2f} zł" if g.best_price_pln else "—"
        img = ""
        if g.cover_image:
            src = html.escape(g.cover_image)
            img = (
                f'<img src="{src}" alt="" width="460" height="215" '
                f'loading="lazy" decoding="async">'
            )
        meta_html = (
            f'<span class="seo-meta">{html.escape(sav.strip())}</span>' if sav else ""
        )
        href = _game_page_url(g.slug)
        title_esc = html.escape(g.title)
        cards += (
            f'<a class="seo-card" href="{href}">'
            f'{img}<span class="seo-card-body"><strong>{title_esc}</strong>'
            f'<span class="seo-price">{price}</span>{meta_html}</span></a>'
        )
        list_items.append(
            {
                "@type": "ListItem",
                "position": i,
                "url": href,
                "name": g.title,
            }
        )
    return cards, list_items


'''

DEALS_TAIL = r'''    exact_title = kind == "budget" and max_price in (10, 20, 30, 50, 100)
    page_title = safe_heading if exact_title else f"{safe_heading} — porównanie cen | KupujPL Gry"
    og_title = safe_heading if exact_title else f"{safe_heading} | KupujPL Gry"
    grid = cards if cards else "<p>Brak gier spełniających kryteria — zajrzyj wkrótce.</p>"
    assets = _site_skin_assets()
    header = _site_skin_header()
    scripts = _site_skin_scripts()
    can_url = html.escape(page_url)
    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{page_title}</title>
<meta name="description" content="{meta_desc}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{can_url}">
<meta property="og:type" content="website">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="{can_url}">
<meta name="twitter:card" content="summary_large_image">
{assets}
<script type="application/ld+json">{item_list_ld}</script>
<script type="application/ld+json">{breadcrumb_ld}</script>
<script type="application/ld+json">{faq_ld}</script>
</head>
<body class="layout-split seo-collection">
{header}
<main class="seo-main">
  <p class="seo-nav-mini"><a href="{SITE_ORIGIN}/">← Katalog</a> · <a href="{SITE_ORIGIN}/promocje">Promocje</a></p>
  <h1>{safe_heading}</h1>
  <p class="seo-lead">{lead}</p>
  {hub}
  <div class="seo-grid">{grid}</div>
  <section class="faq"><h2>Najczęstsze pytania</h2>{faq_html}</section>
  <a class="seo-cta" href="{SITE_ORIGIN}/">Wróć do katalogu</a>
</main>
{scripts}
</body></html>"""


'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "def _site_skin_assets" not in text:
        raise SystemExit("site skin helpers missing")

    c0 = text.find("def _collection_cards")
    c1 = text.find("\ndef _faq_page_schema", c0)
    if c0 < 0 or c1 < 0:
        raise SystemExit("collection cards markers missing")
    text = text[:c0] + NEW_COLLECTION_CARDS + text[c1:]

    start = text.find("def deals_landing_html")
    end = text.find("\ndef dubbing_landing_html", start)
    if start < 0 or end < 0:
        raise SystemExit("deals markers missing")
    chunk = text[start:end]
    marker = '    exact_title = kind == "budget" and max_price in (10, 20, 30, 50, 100)\n'
    if marker not in chunk:
        raise SystemExit("exact_title marker missing")
    pre = chunk.split(marker, 1)[0]
    new_chunk = pre + DEALS_TAIL
    text = text[:start] + new_chunk + text[end:]

    if "seo-collection .faq{{" not in text:
        needle = "  .seo-collection .seo-nav-mini a{{color:inherit}}\n</style>"
        insert = (
            "  .seo-collection .seo-nav-mini a{{color:inherit}}\n"
            "  .seo-collection .faq{{margin:28px 0}}\n"
            "  .seo-collection .faq h2{{font-size:1.25rem;margin-bottom:8px}}\n"
            "  .seo-collection .faq details{{border-bottom:1px solid color-mix(in srgb, var(--text,#e8e6e3) 12%, transparent);padding:8px 0}}\n"
            "  .seo-collection .faq summary{{cursor:pointer;font-weight:600}}\n"
            "  .seo-collection .hub-links{{margin:12px 0 8px;font-size:.9rem;opacity:.85}}\n"
            "  .seo-collection .hub-links a{{color:inherit;margin-right:12px;text-decoration:underline}}\n"
            "</style>"
        )
        if needle not in text:
            raise SystemExit("faq css needle missing")
        text = text.replace(needle, insert, 1)

    ast.parse(text)
    TARGET.write_text(text, encoding="utf-8")
    print("OK", TARGET.stat().st_size)


if __name__ == "__main__":
    main()
