#!/usr/bin/env python3
"""Patch seo_pages.py: category landings use full site skin."""
from __future__ import annotations

import ast
from pathlib import Path

TARGET = Path("/opt/kupujpl-games/app/core/seo_pages.py")

HELPERS = r'''
def _site_skin_assets() -> str:
    """Full KupujPL chrome (style.css + theme) for SEO collection pages."""
    return f"""
<link rel="icon" href="{SITE_ORIGIN}/static/favicon.png?v=1" type="image/png">
<link rel="stylesheet" href="{SITE_ORIGIN}/static/style.css?v=91">
<script>
(function(){{try{{var k=localStorage.getItem('kupujpl-theme');
document.documentElement.dataset.theme=(!k||['night','ice','void','matrix'].indexOf(k)<0)?'night':k;
}}catch(e){{document.documentElement.dataset.theme='night';}}}})();
</script>
<style>
  body.seo-collection{{min-height:100vh}}
  .seo-collection .seo-main{{max-width:1100px;margin:0 auto;padding:20px 16px 48px}}
  .seo-collection .seo-lead{{opacity:.85;margin:8px 0 20px;font-size:1.05rem;line-height:1.55}}
  .seo-collection .seo-grid{{
    display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin:20px 0 28px
  }}
  .seo-collection a.seo-card{{
    display:flex;flex-direction:column;text-decoration:none;color:inherit;
    border:1px solid color-mix(in srgb, var(--text, #e8e6e3) 14%, transparent);
    border-radius:12px;overflow:hidden;background:color-mix(in srgb, var(--bg-elevated, #1a1a22) 88%, transparent);
    transition:transform .15s ease, border-color .15s ease;
  }}
  .seo-collection a.seo-card:hover{{transform:translateY(-2px);border-color:var(--accent,#fcee09)}}
  .seo-collection a.seo-card img{{width:100%;aspect-ratio:460/215;object-fit:cover;display:block;background:#111}}
  .seo-collection a.seo-card .seo-card-body{{padding:10px 12px 12px}}
  .seo-collection a.seo-card strong{{display:block;font-size:.95rem;line-height:1.3;margin-bottom:4px}}
  .seo-collection a.seo-card .seo-price{{font-weight:700;color:var(--accent,#fcee09)}}
  .seo-collection a.seo-card .seo-meta{{opacity:.7;font-size:.8rem;display:block;margin-top:2px}}
  .seo-collection .seo-cta{{
    display:inline-block;margin-top:8px;padding:12px 18px;border-radius:10px;font-weight:700;
    background:var(--accent,#fcee09);color:#111;text-decoration:none
  }}
  .seo-collection .seo-nav-mini{{opacity:.75;font-size:.9rem;margin-bottom:12px}}
  .seo-collection .seo-nav-mini a{{color:inherit}}
</style>
"""


def _site_skin_header() -> str:
    return f"""
<header class="header">
  <div class="wrap header-inner">
    <a href="{SITE_ORIGIN}/" class="brand">
      <span class="brand-name">Kupuj<span class="brand-accent">PL</span></span>
      <span class="brand-sub">Gry</span>
    </a>
    <nav class="header-info" aria-label="Informacje">
      <a href="{SITE_ORIGIN}/o-nas" class="header-info-btn">O nas</a>
      <a href="{SITE_ORIGIN}/promocje" class="header-info-btn">Promocje</a>
      <a href="{SITE_ORIGIN}/kontakt" class="header-info-btn">Kontakt</a>
    </nav>
    <nav id="auth-nav" class="auth-nav"></nav>
  </div>
</header>
"""


def _site_skin_scripts() -> str:
    return f"""
<script src="{SITE_ORIGIN}/static/i18n.js?v=28"></script>
<script src="{SITE_ORIGIN}/static/theme.js?v=2"></script>
<script src="{SITE_ORIGIN}/static/matrix-rain.js?v=3"></script>
<script src="{SITE_ORIGIN}/static/cookie-consent.js?v=2"></script>
<script src="{SITE_ORIGIN}/static/core-bundle.js?v=12"></script>
"""


'''

NEW_CATEGORY = r'''def category_landing_html(*, category, games: list[GameListResponse]) -> str:
    page_url = f"{SITE_ORIGIN}/kategoria/{category.slug}"
    safe_name = html.escape(category.name)
    cheapest = min(
        (g.best_price_pln for g in games if g.best_price_pln), default=None
    )
    price_bit = f" już od {cheapest:.2f} zł" if cheapest else ""
    meta_plain = _clip_text(
        f"Gry {category.name} na PC{price_bit} — porównaj ceny w sklepach: "
        "Steam, GOG, Epic i sklepy z kluczami. Aktualne promocje i historia cen.",
        160,
    )
    meta_desc = html.escape(meta_plain)

    cards = ""
    list_items = []
    for i, g in enumerate(games, start=1):
        label = html.escape(g.lowest_ever_label or "")
        price = f"{g.best_price_pln:.2f} zł" if g.best_price_pln else "—"
        img = ""
        cover = getattr(g, "cover_image", None)
        if cover:
            src = html.escape(cover)
            img = (
                f'<img src="{src}" alt="" width="460" height="215" '
                f'loading="lazy" decoding="async">'
            )
        meta_html = f'<span class="seo-meta">{label}</span>' if label else ""
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

    item_list_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": f"Gry: {category.name}",
            "url": page_url,
            "description": meta_plain,
            "mainEntity": {"@type": "ItemList", "itemListElement": list_items},
        },
        ensure_ascii=False,
    )
    breadcrumb_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "KupujPL Gry", "item": SITE_ORIGIN + "/"},
                {"@type": "ListItem", "position": 2, "name": "Kategorie", "item": SITE_ORIGIN + "/kategorie"},
                {"@type": "ListItem", "position": 3, "name": category.name, "item": page_url},
            ],
        },
        ensure_ascii=False,
    )
    og_image = f"{SITE_ORIGIN}/og/logo.png"
    grid = cards if cards else "<p>Brak gier w kategorii.</p>"
    assets = _site_skin_assets()
    header = _site_skin_header()
    scripts = _site_skin_scripts()
    can_url = html.escape(page_url)
    cat_slug = html.escape(category.slug)
    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Gry {safe_name} — ceny, porównanie sklepów PC | KupujPL Gry</title>
<meta name="description" content="{meta_desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{can_url}">
<meta property="og:type" content="website">
<meta property="og:title" content="Gry {safe_name} — KupujPL Gry">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="{can_url}">
<meta name="twitter:card" content="summary_large_image">
{assets}
<script type="application/ld+json">{item_list_ld}</script>
<script type="application/ld+json">{breadcrumb_ld}</script>
</head>
<body class="layout-split seo-collection">
{header}
<main class="seo-main">
  <p class="seo-nav-mini"><a href="{SITE_ORIGIN}/">← Katalog</a> · <a href="{SITE_ORIGIN}/promocje">Promocje</a></p>
  <h1>Gry: {safe_name}</h1>
  <p class="seo-lead">Porównaj ceny gier z kategorii „{safe_name}” w polskich sklepach PC. Steam, GOG, Epic i sklepy z kluczami.</p>
  <div class="seo-grid">{grid}</div>
  <a class="seo-cta" href="{SITE_ORIGIN}/?category={cat_slug}">Pełny katalog</a>
</main>
{scripts}
</body></html>"""


'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "def _site_skin_assets" in text:
        h0 = text.find("def _site_skin_assets")
        c0 = text.find("def category_landing_html(")
        if 0 <= h0 < c0:
            text = text[:h0] + text[c0:]

    start = text.find("def category_landing_html(")
    end = text.find("\ndef deals_landing_html(", start)
    if start < 0 or end < 0:
        raise SystemExit(f"markers not found: start={start} end={end}")

    # Validate fragment alone by wrapping
    fragment = HELPERS + NEW_CATEGORY
    ast.parse(fragment)

    out = text[:start] + HELPERS + NEW_CATEGORY + text[end:]
    ast.parse(out)
    TARGET.write_text(out, encoding="utf-8")
    print("OK", TARGET, "bytes", TARGET.stat().st_size)


if __name__ == "__main__":
    main()
