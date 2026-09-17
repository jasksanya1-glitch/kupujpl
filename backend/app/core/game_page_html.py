"""Interactive full game page HTML (replaces modal UX)."""
from __future__ import annotations

import html
import json
from datetime import date, timedelta

from app.core.seo_pages import price_history_svg
from app.core.site_config import SITE_ORIGIN
from app.core.worth_buy import compute_worth_buy, worth_buy_html
from app.schemas.schemas import OfferResponse


def _game_page_url(slug: str) -> str:
    return f"{SITE_ORIGIN}/gra/{slug}"


def game_interactive_html(
    *,
    title: str,
    slug: str,
    description: str | None,
    cover_image: str | None,
    best_price_pln: float | None,
    best_shop_name: str | None,
    steam_price_pln: float | None = None,
    savings_pln: float | None = None,
    savings_pct: int | None = None,
    offers: list[OfferResponse] | None = None,
    history: list[dict] | None = None,
    lowest_ever_pln: float | None = None,
    avg_best_price_30d: float | None = None,
    lowest_ever_label: str | None = None,
    at_historical_low: bool = False,
    related_dlc: list[dict] | None = None,
    parent_game: dict | None = None,
    related_games: list[dict] | None = None,
    category_slug: str | None = None,
    category_name: str | None = None,
    indexable: bool = True,
) -> str:
    page_url = _game_page_url(slug)
    hist_url = f"{SITE_ORIGIN}/historia-cen/{slug}"
    safe_title = html.escape(title)
    robots = "index, follow" if indexable else "noindex, follow"
    img = html.escape(cover_image or f"{SITE_ORIGIN}/static/favicon.ico")
    home = html.escape(SITE_ORIGIN + "/")

    page_title = f"{title} – cena, najtaniej, promocje | KupujPL"
    h1_text = f"{title} – gdzie najtaniej?"
    safe_page_title = html.escape(page_title)
    safe_h1 = html.escape(h1_text)

    if best_price_pln is not None:
        shop_bit = f" w {best_shop_name}" if best_shop_name else ""
        meta_plain = (
            f"{title} – porównaj ceny w sklepach. Najtaniej od {best_price_pln:.2f} zł{shop_bit}. "
            f"Sprawdź historię cen, promocje i oszczędność względem Steam."
        )
    else:
        meta_plain = (
            f"{title} – porównaj ceny w sklepach PC. Sprawdź historię cen, promocje "
            f"i aktualne oferty na KupujPL."
        )
    meta_plain = meta_plain[:160]
    meta_desc = html.escape(meta_plain)

    seo_bits: list[str] = []
    if best_price_pln is not None:
        shop_bit = f" ({html.escape(best_shop_name)})" if best_shop_name else ""
        seo_bits.append(
            f"<strong>{safe_title}</strong> kosztuje obecnie od "
            f"<strong>{best_price_pln:.2f} zł</strong>{shop_bit}."
        )
    if steam_price_pln and savings_pct and savings_pln:
        seo_bits.append(
            f"Na Steam: {steam_price_pln:.2f} zł — oszczędzasz {savings_pln:.2f} zł (−{savings_pct}%)."
        )
    elif steam_price_pln:
        seo_bits.append(f"Cena Steam: {steam_price_pln:.2f} zł.")
    if lowest_ever_pln:
        seo_bits.append(f"Historyczne minimum: {lowest_ever_pln:.2f} zł.")
    if avg_best_price_30d:
        seo_bits.append(f"Średnia 30 dni: {avg_best_price_30d:.2f} zł.")
    if not seo_bits:
        seo_bits.append(
            f"Sprawdź aktualne ceny {safe_title} w sklepach PC, historię cen i promocje."
        )
    seo_summary_html = (
        '<section class="game-seo-summary" id="gp-seo-summary">'
        f'<p>{" ".join(seo_bits)} '
        "Porównaj oferty, zobacz wykres historii cen i włącz alert spadku ceny.</p>"
        "</section>"
    )

    hist_badge = ""
    if at_historical_low or lowest_ever_label:
        label = lowest_ever_label or "najniższa cena w historii"
        hist_badge = f'<span class="hist-low-badge">{html.escape(label)}</span>'

    savings_html = ""
    if savings_pln and savings_pct and steam_price_pln:
        savings_html = (
            f'<p class="game-page-savings" data-savings-pln="{savings_pln:.2f}" '
            f'data-savings-pct="{savings_pct}" data-steam-pln="{steam_price_pln:.2f}">'
            f"Oszczędzasz {savings_pln:.2f} zł (−{savings_pct}%) vs Steam ({steam_price_pln:.2f} zł)</p>"
        )

    offer_list = list(offers or [])
    offer_rows = ""
    for o in offer_list:
        trust_key = "card.official" if o.is_official else "card.marketplace"
        trust_fallback = "Oficjalny" if o.is_official else "Marketplace"
        go = f"{SITE_ORIGIN}/api/go/{o.id}"
        kind = "official" if o.is_official else "keyshop"
        offer_rows += (
            f'<div class="offer-row" data-shop-kind="{kind}">'
            f'<div class="offer-shop"><strong>{html.escape(o.shop_name)}</strong>'
            f'<span class="badge" data-i18n="{trust_key}">{trust_fallback}</span></div>'
            f'<div class="offer-price">{o.price_pln:.2f} zł</div>'
            f'<a class="btn-buy" href="{html.escape(go)}" rel="noopener noreferrer sponsored" '
            f'target="_blank" data-i18n="offer.buy">Kup</a>'
            f"</div>"
        )

    # Immediate answer strip: price / shop / buy / "Czy warto kupić?" score
    answer_html = ""
    if best_price_pln is not None:
        shop = html.escape(best_shop_name or "")
        buy_href = ""
        if offer_list:
            buy_href = html.escape(f"{SITE_ORIGIN}/api/go/{offer_list[0].id}")
        worth = compute_worth_buy(
            current_price=best_price_pln,
            avg_best_price_30d=avg_best_price_30d,
            lowest_ever_pln=lowest_ever_pln,
            steam_price_pln=steam_price_pln,
            savings_pct=savings_pct,
            at_historical_low=at_historical_low,
        )
        verdict = worth_buy_html(worth)
        buy_btn = ""
        if buy_href:
            buy_btn = (
                f'<a class="btn-buy game-page-answer-buy" href="{buy_href}" '
                f'rel="noopener noreferrer sponsored" target="_blank" '
                f'data-i18n="game.buy_cheapest">Kup najtaniej</a>'
            )
        answer_html = (
            '<div class="game-page-answer" id="gp-answer">'
            '<div class="game-page-answer-row">'
            '<div class="game-page-answer-price">'
            '<span class="game-page-answer-label" data-i18n="game.from">od</span> '
            f'<strong id="gp-best-price">{best_price_pln:.2f} zł</strong>'
            f'<span class="game-page-answer-shop"> · {shop}</span>'
            "</div>"
            f"{buy_btn}"
            "</div>"
            f"{verdict}"
            f"{savings_html}"
            f"{hist_badge}"
            "</div>"
        )

    def _related_tiles(items: list[dict]) -> str:
        tiles = ""
        for g in items:
            gurl = f"{SITE_ORIGIN}/gra/{html.escape(g.get('slug') or '')}"
            gcover = html.escape(g.get("cover_image") or "")
            gtitle = html.escape(g.get("title") or "")
            price = g.get("best_price_pln")
            price_txt = f"{float(price):.2f} zł" if price is not None else "—"
            tiles += (
                f'<a class="dlc-tile game-card game-card-row" href="{gurl}">'
                f'<span class="card-cover"><img src="{gcover}" alt="{gtitle}" loading="lazy" width="196" height="92"></span>'
                f'<span class="card-body"><span class="card-title">{gtitle}</span>'
                f'<span class="card-price">{price_txt}</span></span></a>'
            )
        return tiles

    def _related_section(css: str, i18n_key: str, fallback_title: str, items: list[dict]) -> str:
        return (
            f'<section class="{css}">'
            f'<div class="home-section-head"><div>'
            f'<h2 class="home-section-title gp-related-title" data-i18n="{i18n_key}">{fallback_title}</h2>'
            f"</div></div>"
            f'<div class="dlc-row home-section-row">{_related_tiles(items)}</div></section>'
        )

    parent_html = ""
    if parent_game and parent_game.get("slug"):
        parent_html = _related_section(
            "game-dlc game-parent home-feed-block home-section-block",
            "game.parent_title",
            "Gra podstawowa",
            [parent_game],
        )

    dlc_html = ""
    if related_dlc:
        dlc_html = _related_section(
            "game-dlc home-feed-block home-section-block",
            "game.dlc_title",
            "DLC i edycje",
            related_dlc,
        )

    similar_html = ""
    if related_games:
        similar_html = _related_section(
            "game-similar home-feed-block home-section-block",
            "game.similar_title",
            "Podobne gry",
            related_games,
        )

    history_meta = ""
    if lowest_ever_pln:
        history_meta = f"Najniższa w historii: {lowest_ever_pln:.2f} zł"
        if avg_best_price_30d:
            history_meta += f" · średnia 30 dni: {avg_best_price_30d:.2f} zł"

    chart = price_history_svg(history, title=f"Historia cen {title}", width=720, height=240)
    history_section = ""
    if chart or (history and len(history) >= 2):
        table_rows = ""
        for p in (history or [])[-14:]:
            table_rows += (
                f"<tr><td>{html.escape(str(p.get('date') or ''))}</td>"
                f"<td>{float(p['best_price_pln']):.2f} zł</td></tr>"
            )
        history_section = (
            '<section class="game-price-history" id="historia-cen">'
            f"{chart}"
            f'<p id="gp-history-meta" class="muted">{html.escape(history_meta)}</p>'
            f'<p class="muted"><a href="{html.escape(hist_url)}">Pełna historia cen {safe_title}</a></p>'
            '<noscript><table class="history-table"><thead><tr><th>Dzień</th><th>Cena</th></tr></thead>'
            f"<tbody>{table_rows}</tbody></table></noscript>"
            "</section>"
        )
    elif history_meta:
        history_section = f'<p id="gp-history-meta" class="muted">{html.escape(history_meta)}</p>'

    desc_plain = (description or "").strip()
    desc_block = ""
    if desc_plain:
        desc_block = (
            '<div class="game-page-desc-block">'
            '<p class="game-page-desc-label" data-i18n="game.desc_toggle">Opis gry</p>'
            f'<p id="gp-desc" class="game-page-desc">{html.escape(desc_plain[:520])}</p>'
            "</div>"
        )

    media_aside = (
        '<aside class="game-media-aside">'
        f'<figure class="game-page-cover"><img id="gp-cover" src="{img}" alt="{safe_title}" width="460" height="215"></figure>'
        f"{desc_block}"
        "</aside>"
    )
    media_row = (
        '<div class="game-media-block">'
        '<h2 class="offers-title game-media-title">Historia cen</h2>'
        '<div class="game-media-row">'
        f'<div class="game-media-history">{history_section}</div>'
        f"{media_aside}"
        "</div></div>"
        if history_section
        else (
            '<div class="game-media-block">'
            f'<div class="game-media-row game-media-row--solo">{media_aside}</div></div>'
        )
    )

    bootstrap = {
        "slug": slug,
        "title": title,
        "lowest_ever_pln": lowest_ever_pln,
        "at_historical_low": at_historical_low,
        "lowest_ever_label": lowest_ever_label,
    }

    product = {
        "@context": "https://schema.org",
        "@type": ["Product", "VideoGame"],
        "name": title,
        "description": meta_plain,
        "url": page_url,
        "gamePlatform": "PC",
        "image": cover_image or None,
    }
    if best_price_pln:
        product["offers"] = {
            "@type": "AggregateOffer",
            "priceCurrency": "PLN",
            "lowPrice": f"{best_price_pln:.2f}",
            "availability": "https://schema.org/InStock",
            "url": page_url,
            "priceValidUntil": (date.today() + timedelta(days=7)).isoformat(),
        }
    json_ld = json.dumps(product, ensure_ascii=False)

    crumb_items = [
        {"@type": "ListItem", "position": 1, "name": "Gry PC", "item": SITE_ORIGIN + "/"},
    ]
    breadcrumb_html_parts = [
        f'<a href="{home}">Gry PC</a>',
    ]
    if category_slug and category_name:
        cat_url = f"{SITE_ORIGIN}/kategoria/{category_slug}"
        crumb_items.append(
            {
                "@type": "ListItem",
                "position": 2,
                "name": category_name,
                "item": cat_url,
            }
        )
        breadcrumb_html_parts.append(
            f'<a href="{html.escape(cat_url)}">{html.escape(category_name)}</a>'
        )
        crumb_items.append(
            {"@type": "ListItem", "position": 3, "name": title, "item": page_url}
        )
    else:
        crumb_items.append(
            {"@type": "ListItem", "position": 2, "name": title, "item": page_url}
        )
    breadcrumb_html_parts.append(f"<span>{safe_title}</span>")
    breadcrumb_html = " / ".join(breadcrumb_html_parts)

    hub_links = [
        ("gry-pc-do-30-zl", "Gry PC do 30 zł"),
        ("promocje", "Promocje"),
        ("gdzie-kupic-gry-pc-najtaniej", "Gdzie kupić najtaniej"),
    ]
    if category_slug and category_name:
        hub_links.insert(0, (f"kategoria/{category_slug}", category_name))
    seo_hub_html = (
        '<nav class="game-seo-hub" aria-label="Powiązane strony">'
        + "".join(
            f'<a href="{html.escape(SITE_ORIGIN + "/" + href)}">{html.escape(label)}</a>'
            for href, label in hub_links
        )
        + "</nav>"
    )

    breadcrumb_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": crumb_items,
        },
        ensure_ascii=False,
    )

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="kupujpl-page" content="seo-v3">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <base href="/games/">
  <title>{safe_page_title}</title>
  <meta name="description" content="{meta_desc}">
  <meta name="robots" content="{robots}">
  <link rel="canonical" href="{html.escape(page_url)}">
  <link rel="alternate" hreflang="pl" href="{html.escape(page_url)}">
  <link rel="alternate" hreflang="uk" href="{html.escape(page_url)}">
  <link rel="alternate" hreflang="en" href="{html.escape(page_url)}">
  <link rel="alternate" hreflang="x-default" href="{html.escape(page_url)}">
  <meta property="og:title" content="{safe_page_title}">
  <meta property="og:description" content="{meta_desc}">
  <meta property="og:image" content="{SITE_ORIGIN}/og/gra/{html.escape(slug)}.png">
  <meta property="og:url" content="{html.escape(page_url)}">
  <link rel="icon" href="static/favicon.png?v=1" type="image/png">
  <link rel="shortcut icon" href="static/favicon.ico?v=1">
  <link rel="icon" href="static/favicon.ico?v=1" sizes="any">
  <link rel="stylesheet" href="static/style.css?v=91">
  <style>
    .game-page{{padding:8px 14px 48px;max-width:1100px!important;margin:0 auto!important;width:100%;box-sizing:border-box}}
    .game-breadcrumb{{font-size:12px;margin:0 0 6px;opacity:.8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
    .game-breadcrumb a{{color:inherit}}
    .game-page-head{{display:flex;flex-direction:column;gap:8px;margin-bottom:10px}}
    .game-page-head h1{{margin:0;font-size:clamp(1.4rem,2.5vw,1.9rem);line-height:1.15;text-transform:none;overflow-wrap:anywhere;color:#f7f4e8!important;text-shadow:0 1px 2px rgba(0,0,0,.85)}}
    .game-seo-summary{{margin:0 0 10px;padding:10px 12px;border:1px solid rgba(255,255,255,.12);border-radius:8px;background:rgba(0,0,0,.28)}}
    .game-seo-summary p{{margin:0;font-size:.92rem;line-height:1.45;color:#e8e2d2!important;text-transform:none!important}}
    .game-seo-hub{{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 4px}}
    .game-seo-hub a{{font-size:.82rem;color:var(--cp-cyan,#00f0ff)!important;text-decoration:underline;text-underline-offset:2px}}
    .game-page-answer{{margin:0 0 10px;padding:12px 14px;border:1px solid rgba(255,214,64,.45);border-radius:10px;background:rgba(6,10,16,.88);box-shadow:0 8px 24px rgba(0,0,0,.35)}}
    .game-page-answer-row{{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px}}
    .game-page-answer-price{{font-size:1.2rem;line-height:1.2;color:#f7f4e8!important}}
    .game-page-answer-price strong{{font-size:1.85rem;letter-spacing:-.02em;color:#7fd7ff!important}}
    .game-page-answer-label,.game-page-answer-shop{{opacity:.95;font-size:1rem;color:#f0ecd8!important}}
    .game-page-answer-buy{{flex-shrink:0}}
    .worth-buy{{margin:10px 0 0;padding:10px 12px;border-radius:8px;border:1px solid rgba(255,255,255,.14);background:rgba(0,0,0,.28)}}
    .worth-buy-kicker{{margin:0 0 4px;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;opacity:.75;color:#f0ecd8!important}}
    .worth-buy-score{{margin:0;font-size:1.15rem;line-height:1.25;color:#f7f4e8!important}}
    .worth-buy-points{{font-size:1.35rem;letter-spacing:-.02em}}
    .worth-buy-label{{font-weight:700;letter-spacing:.02em}}
    .worth-buy-reason{{margin:6px 0 0;font-size:.92rem;line-height:1.35;color:#f0ecd8!important;opacity:.95}}
    .worth-buy.is-buy{{border-color:rgba(184,255,87,.45);background:rgba(40,90,20,.28)}}
    .worth-buy.is-buy .worth-buy-points,.worth-buy.is-buy .worth-buy-label{{color:#b8ff57!important}}
    .worth-buy.is-maybe{{border-color:rgba(255,210,122,.4);background:rgba(90,70,10,.28)}}
    .worth-buy.is-maybe .worth-buy-points,.worth-buy.is-maybe .worth-buy-label{{color:#ffd27a!important}}
    .worth-buy.is-wait{{border-color:rgba(255,100,100,.4);background:rgba(90,20,20,.28)}}
    .worth-buy.is-wait .worth-buy-points,.worth-buy.is-wait .worth-buy-label{{color:#ff8a8a!important}}
    .game-page-savings,.hist-low-badge{{margin:6px 0 0;display:inline-block;color:#f0ecd8!important}}
    /* History + cover share one row; offers stay full width below */
    .game-media-block{{margin:0 0 14px}}
    .game-media-title{{margin:0 0 8px;font-size:.95rem}}
    .game-media-row{{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;align-items:start}}
    .game-media-history{{min-width:0}}
    .game-media-aside{{min-width:0;display:flex;flex-direction:column;gap:10px}}
    .game-price-history{{margin:0}}
    .game-price-history .price-chart{{margin:0;width:100%}}
    .game-price-history .price-chart svg{{display:block;width:100%!important;height:auto!important;max-height:250px!important;aspect-ratio:720 / 240}}
    .game-price-history .ph-legend{{display:flex;flex-wrap:wrap;gap:6px 10px;margin:6px 0 2px;font-size:10px;text-transform:uppercase;letter-spacing:.04em}}
    .game-price-history .ph-leg{{display:inline-flex;align-items:center;gap:5px;color:var(--cp-white,#f8f6dc)}}
    .game-price-history .ph-leg::before{{content:"";width:8px;height:8px;border:1px solid currentColor;background:currentColor}}
    .game-price-history .ph-leg-low{{color:var(--cp-cyan,#00f0ff)}}
    .game-price-history .ph-leg-avg{{color:var(--cp-yellow,#fcee09)}}
    .game-price-history .ph-leg-avg::before{{background:transparent;border-top-width:2px;height:0;width:12px}}
    .game-price-history .ph-leg-high{{color:var(--cp-red,#ff003c)}}
    .game-price-history .ph-leg-now{{color:var(--cp-yellow,#fcee09)}}
    .game-price-history .ph-caption{{margin-top:2px;font-size:11px;color:var(--cp-white,#f8f6dc)!important;opacity:.8}}
    .game-price-history .muted{{margin:2px 0;font-size:11px}}
    .game-price-history .muted a{{color:var(--cp-cyan,#00f0ff)!important}}
    .game-page-cover{{margin:0;border-radius:8px;overflow:hidden;border:1px solid rgba(255,255,255,.12);height:240px}}
    .game-page-cover img{{width:100%!important;max-width:100%!important;height:240px!important;object-fit:cover;object-position:center top;display:block;border-radius:0}}
    .game-page-desc-block{{min-width:0;padding:10px 12px;border:1px solid rgba(255,255,255,.1);border-radius:8px;background:rgba(0,0,0,.35)}}
    .game-page-desc-label{{margin:0 0 6px;font-size:.72rem;letter-spacing:.06em;text-transform:uppercase;opacity:.72;color:#f0ecd8!important}}
    .game-page-desc{{margin:0;font-size:.9rem;line-height:1.45;color:#e8e2d2!important;text-transform:none!important;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical;overflow:hidden}}
    .game-page-prices{{margin-top:2px}}
    .game-page-prices .offers-title{{margin:0 0 8px}}
    .game-page-actions{{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 4px}}
    @media (max-width:900px){{
      .game-media-row{{grid-template-columns:1fr;gap:12px}}
      .game-media-aside{{flex-direction:row;align-items:stretch}}
      .game-page-cover{{flex:0 0 180px;height:120px}}
      .game-page-cover img{{height:120px!important}}
      .game-page-desc-block{{flex:1;min-width:0}}
      .game-price-history .price-chart svg{{max-height:180px!important}}
    }}
    @media (max-width:768px){{
      .game-page{{padding:6px 10px 88px}}
      .game-page-answer{{padding:10px 12px}}
      .game-page-answer-price strong{{font-size:1.65rem}}
      .game-page-answer-buy{{width:100%;text-align:center}}
      .game-media-aside{{flex-direction:column}}
      .game-page-cover{{flex:none;height:160px}}
      .game-page-cover img{{height:160px!important}}
      .offer-row{{grid-template-columns:1fr auto;gap:8px;padding:10px;clip-path:none}}
      .offer-row .btn-buy{{grid-column:1 / -1;width:100%}}
    }}
  </style>
  <script>try{{var t=localStorage.getItem('kupujpl-theme');document.documentElement.dataset.theme=(!t||['night','ice','void','matrix'].indexOf(t)<0)?'night':t;}}catch(e){{document.documentElement.dataset.theme='night';}}</script>
  <script type="application/ld+json">{json_ld}</script>
  <script type="application/ld+json">{breadcrumb_ld}</script>
</head>
<body class="layout-split game-page-body">
  <header class="header">
    <div class="wrap header-inner">
      <a href="{home}" class="brand">
        <span class="brand-name">Kupuj<span class="brand-accent">PL</span></span>
        <span class="brand-sub">Gry</span>
      </a>
      <a class="header-info-btn" href="{home}" data-i18n="game.back">← Katalog</a>
      <nav id="auth-nav" class="auth-nav"></nav>
    </div>
  </header>

  <main class="game-page wrap">
    <nav class="game-breadcrumb">{breadcrumb_html}</nav>
    <header class="game-page-head">
      <h1 id="gp-title">{safe_h1}</h1>
      {seo_summary_html}
      {answer_html}
    </header>

    {media_row}

    <div class="game-page-prices">
      <h2 class="offers-title" data-i18n="modal.prices">Ceny w sklepach</h2>
      <div id="gp-offers" class="offers game-page-offers">{offer_rows or '<p class="offers-empty" data-i18n="offer.refreshing">Brak ofert — odświeżamy…</p>'}</div>
    </div>

    <div class="game-page-actions">
      <button type="button" id="btn-favorite" class="btn-watch" data-i18n="card.watch">Śledź</button>
      <button type="button" id="btn-alert-toggle" class="btn-alert" data-i18n="modal.alert">Alert cenowy</button>
    </div>

    <div id="alert-panel" class="alert-panel" hidden>
      <label class="alert-field">
        <span data-i18n="alert.target">Celowa cena (zł)</span>
        <input type="number" id="alert-target" min="0" step="0.01" placeholder="np. 49.99">
      </label>
      <label class="alert-field">
        <span data-i18n="alert.shops">Sklepy</span>
        <select id="alert-shop-filter">
          <option value="any" data-i18n="alert.shops_any">Wszystkie</option>
          <option value="official" data-i18n="alert.shops_official">Tylko oficjalne</option>
          <option value="keyshop" data-i18n="alert.shops_keyshop">Tylko keyshopy</option>
        </select>
      </label>
      <button type="button" id="btn-alert-save" class="cp-btn" data-i18n="alert.save">Zapisz alert</button>
      <button type="button" id="btn-alert-off" class="btn-secondary" data-i18n="alert.off">Wyłącz</button>
    </div>

    <div id="gp-related" class="game-page-related"{'' if (parent_html or dlc_html or similar_html) else ' hidden'}>
      {parent_html}
      {dlc_html}
      {similar_html}
    </div>
    {seo_hub_html}
  </main>

  <footer class="footer">
    <div class="wrap footer-inner">
      <nav class="footer-nav" aria-label="SEO">
        <a href="gry-pc-do-30-zl" class="footer-btn">Gry PC do 30 zł</a>
        <a href="promocje" class="footer-btn">Promocje</a>
        <a href="gdzie-kupic-gry-pc-najtaniej" class="footer-btn">Gdzie kupić najtaniej</a>
        <a href="gry-z-polskim-dubbingiem" class="footer-btn" id="footer-seo-dubbing">Gry z polskim dubbingiem</a>
        <a href="{html.escape(hist_url)}" class="footer-btn">Historia cen</a>
      </nav>
      <p data-i18n="footer.copy">&copy; 2026 KupujPL · Porównywarka cen gier PC</p>
    </div>
  </footer>

  <script>window.__GAME_BOOTSTRAP__ = {json.dumps(bootstrap, ensure_ascii=False)};</script>
  <script src="static/i18n.js?v=27"></script>
  <script src="static/theme.js?v=2"></script>
  <script src="static/matrix-rain.js?v=3"></script>
  <script src="static/region.js?v=5"></script>
  <script src="static/cookie-consent.js?v=2"></script>
  <script src="static/site-chat.js?v=3"></script>
  <script src="static/umami-loader.js?v=1"></script>
  <script src="static/core-bundle.js?v=8"></script>
  <script src="static/game_page.js?v=13"></script>
</body>
</html>"""
