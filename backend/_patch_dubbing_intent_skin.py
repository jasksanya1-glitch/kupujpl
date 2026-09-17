#!/usr/bin/env python3
"""Skin dubbing + intent guide SEO landings."""
from __future__ import annotations

import ast
from pathlib import Path

TARGET = Path("/opt/kupujpl-games/app/core/seo_pages.py")

DUBBING_TAIL = r'''    og_image = f"{SITE_ORIGIN}/og/logo.png"
    grid = cards if cards else "<p>Trwa uzupełnianie listy — wróć wkrótce.</p>"
    assets = _site_skin_assets()
    header = _site_skin_header()
    scripts = _site_skin_scripts()
    can_url = html.escape(page_url)
    alt_url = html.escape(hreflang_alt)
    related_esc = html.escape(related)
    cta_esc = html.escape(cta)
    og_locale = "uk_UA" if lang == "uk" else "pl_PL"
    og_locale_alt = "pl_PL" if lang == "uk" else "uk_UA"
    return f"""<!DOCTYPE html>
<html lang="{html_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{safe_heading}</title>
<meta name="description" content="{meta_desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{can_url}">
<link rel="alternate" hreflang="pl" href="{SITE_ORIGIN}/gry-z-polskim-dubbingiem">
<link rel="alternate" hreflang="uk" href="{SITE_ORIGIN}/igry-z-polskim-dublyazhem">
<link rel="alternate" hreflang="x-default" href="{SITE_ORIGIN}/gry-z-polskim-dubbingiem">
<meta property="og:type" content="website">
<meta property="og:locale" content="{og_locale}">
<meta property="og:locale:alternate" content="{og_locale_alt}">
<meta property="og:title" content="{safe_heading}">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="{can_url}">
{assets}
<script type="application/ld+json">{item_list_ld}</script>
<script type="application/ld+json">{faq_ld}</script>
</head>
<body class="layout-split seo-collection">
{header}
<main class="seo-main">
  <p class="seo-nav-mini"><a href="{SITE_ORIGIN}/">← Katalog</a> · <a href="{alt_url}">{related_esc}</a></p>
  <h1>{safe_heading}</h1>
  <p class="seo-lead">{lead}</p>
  <p class="hub-links">
    <a href="{SITE_ORIGIN}/gry-pc-do-30-zl">Gry PC do 30 zł</a>
    <a href="{SITE_ORIGIN}/promocje">Promocje</a>
    <a href="{alt_url}">{related_esc}</a>
  </p>
  <div class="seo-grid">{grid}</div>
  <section class="faq"><h2>FAQ</h2>{faq_html}</section>
  <a class="seo-cta" href="{SITE_ORIGIN}/">{cta_esc}</a>
</main>
{scripts}
</body></html>"""


'''

INTENT_FN = r'''def intent_guide_landing_html(*, indexable: bool = True, hub_html: str | None = None) -> str:
    """Editorial intent page: gdzie kupić gry PC najtaniej."""
    from app.core.seo_landings import intent_hub_html

    data = intent_hub_html()
    if hub_html:
        data = {**data, "hub": hub_html}
    page_url = f"{SITE_ORIGIN}/gdzie-kupic-gry-pc-najtaniej"
    heading = data["title"]
    safe_heading = html.escape(heading)
    meta_plain = _clip_text(
        "Gdzie kupić gry PC najtaniej w Polsce — porównaj Steam, GOG, Epic i keyshopy. "
        "Budżetowe listy, przeceny vs Steam i alerty cenowe na KupujPL.",
        160,
    )
    meta_desc = html.escape(meta_plain)
    robots = "index, follow" if indexable else "noindex, follow"
    sections = "".join(
        f'<section class="seo-section"><h2>{html.escape(title)}</h2>'
        f"<p>{html.escape(body)}</p></section>"
        for title, body in data["sections"]
    )
    breadcrumb_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "KupujPL Gry", "item": SITE_ORIGIN + "/"},
                {"@type": "ListItem", "position": 2, "name": heading, "item": page_url},
            ],
        },
        ensure_ascii=False,
    )
    assets = _site_skin_assets()
    header = _site_skin_header()
    scripts = _site_skin_scripts()
    can_url = html.escape(page_url)
    lead = html.escape(data["lead"])
    hub = data["hub"]
    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>{safe_heading} — KupujPL Gry</title>
<meta name="description" content="{meta_desc}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{can_url}">
{assets}
<style>
  .seo-collection .seo-section{{margin:20px 0}}
  .seo-collection .seo-section h2{{font-size:1.2rem;margin:0 0 8px}}
  .seo-collection .seo-hub .hub-group{{margin:8px 0;line-height:1.6}}
  .seo-collection .seo-hub .hub-label{{font-weight:700;margin-right:6px}}
  .seo-collection .seo-hub a{{margin:0 2px;color:inherit}}
</style>
<script type="application/ld+json">{breadcrumb_ld}</script>
</head>
<body class="layout-split seo-collection">
{header}
<main class="seo-main">
  <p class="seo-nav-mini"><a href="{SITE_ORIGIN}/">← Katalog</a> · <a href="{SITE_ORIGIN}/promocje">Promocje</a></p>
  <h1>{safe_heading}</h1>
  <p class="seo-lead">{lead}</p>
  {sections}
  {hub}
  <a class="seo-cta" href="{SITE_ORIGIN}/">Przejdź do katalogu</a>
</main>
{scripts}
</body></html>"""
'''


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if "def _site_skin_assets" not in text:
        raise SystemExit("skin helpers missing")

    # Patch dubbing return shell
    d0 = text.find("def dubbing_landing_html")
    d1 = text.find("\ndef freebies_landing_html", d0)
    if d0 < 0 or d1 < 0:
        raise SystemExit("dubbing markers missing")
    chunk = text[d0:d1]
    marker = '    og_image = f"{SITE_ORIGIN}/og/logo.png"\n'
    if marker not in chunk:
        raise SystemExit("dubbing og_image marker missing")
    if "_site_skin_assets" in chunk:
        print("dubbing already skinned")
    else:
        pre = chunk.split(marker, 1)[0]
        text = text[:d0] + pre + DUBBING_TAIL + text[d1:]
        print("dubbing patched")

    # Replace intent_guide entirely (end of file)
    i0 = text.find("def intent_guide_landing_html")
    if i0 < 0:
        raise SystemExit("intent_guide missing")
    text = text[:i0] + INTENT_FN
    if not text.endswith("\n"):
        text += "\n"

    # Ensure scroll fix present
    if "body.layout-split.seo-collection" not in text:
        raise SystemExit("scroll fix missing from skin assets")

    # Avoid inline import lint? The intent_guide already had inline import from seo_landings
    # Keep as-is for parity with existing code.

    ast.parse(text)
    TARGET.write_text(text, encoding="utf-8")
    print("OK", TARGET.stat().st_size)


if __name__ == "__main__":
    main()
