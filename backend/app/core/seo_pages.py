"""SEO: sitemap, robots, SSR landing pages, blog."""
from __future__ import annotations

import html
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.site_config import SITE_ORIGIN
from app.schemas.schemas import GameListResponse, OfferResponse

_BLOG = Path(__file__).resolve().parent.parent / "data" / "blog_posts.json"

DEAL_URLS = [
    ("promocje", "Promocje na gry PC"),
    ("najwieksze-okazje", "Największe okazje vs Steam"),
    ("gry-ponizej-20-zl", "Gry poniżej 20 zł"),
    ("gry-ponizej-50-zl", "Gry poniżej 50 zł"),
    ("gry-ponizej-100-zl", "Gry poniżej 100 zł"),
]


def _game_page_url(slug: str) -> str:
    return f"{SITE_ORIGIN}/gra/{slug}"


def _spa_game_url(slug: str) -> str:
    return f"{SITE_ORIGIN}/?gra={slug}"


def _load_blog_posts() -> dict:
    if not _BLOG.is_file():
        return {}
    return json.loads(_BLOG.read_text(encoding="utf-8"))


def robots_txt() -> str:
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /panel\n"
        "Disallow: /panel3\n"
        "Disallow: /api/\n"
        f"Sitemap: {SITE_ORIGIN}/sitemap.xml\n"
    )


def sitemap_index_xml() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        f"  <sitemap><loc>{xml_escape(SITE_ORIGIN)}/sitemap-games.xml</loc><lastmod>{now}</lastmod></sitemap>",
        f"  <sitemap><loc>{xml_escape(SITE_ORIGIN)}/sitemap-categories.xml</loc><lastmod>{now}</lastmod></sitemap>",
        f"  <sitemap><loc>{xml_escape(SITE_ORIGIN)}/sitemap-deals.xml</loc><lastmod>{now}</lastmod></sitemap>",
        f"  <sitemap><loc>{xml_escape(SITE_ORIGIN)}/sitemap-blog.xml</loc><lastmod>{now}</lastmod></sitemap>",
        "</sitemapindex>",
    ]
    return "\n".join(parts)


def _url_entries(urls: list[tuple[str, str, str, str]]) -> str:
    parts: list[str] = []
    for loc, lastmod, changefreq, priority in urls:
        parts.append(
            f"  <url><loc>{xml_escape(loc)}</loc><lastmod>{lastmod}</lastmod>"
            f"<changefreq>{changefreq}</changefreq><priority>{priority}</priority></url>"
        )
    return "\n".join(parts)


def sitemap_games_xml(db: Session, *, limit: int = 50000) -> str:
    from app.models.models import Game, Offer

    subq = (
        db.query(Offer.game_id, func.max(Offer.updated_at).label("lastmod"))
        .filter(Offer.in_stock.is_(True))
        .group_by(Offer.game_id)
        .subquery()
    )
    rows = (
        db.query(Game.slug, subq.c.lastmod)
        .join(subq, Game.id == subq.c.game_id)
        .order_by(subq.c.lastmod.desc())
        .limit(limit)
        .all()
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls: list[tuple[str, str, str, str]] = [
        (f"{SITE_ORIGIN}/", now, "daily", "1.0"),
    ]
    for slug, lastmod in rows:
        lm = lastmod.strftime("%Y-%m-%d") if lastmod else now
        urls.append((_game_page_url(slug), lm, "weekly", "0.7"))
    header = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    return "\n".join(header + [_url_entries(urls), "</urlset>"])


def sitemap_categories_xml(db: Session) -> str:
    from app.models.models import Category

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cats = db.query(Category).filter(Category.game_count > 0).order_by(Category.slug).all()
    urls: list[tuple[str, str, str, str]] = []
    for cat in cats:
        urls.append((f"{SITE_ORIGIN}/kategoria/{cat.slug}", now, "weekly", "0.6"))
    header = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    return "\n".join(header + [_url_entries(urls), "</urlset>"])


def sitemap_deals_xml(db: Session) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [(f"{SITE_ORIGIN}/{path}", now, "daily", "0.8") for path, _ in DEAL_URLS]
    header = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    return "\n".join(header + [_url_entries(urls), "</urlset>"])


def sitemap_blog_xml() -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    posts = _load_blog_posts()
    urls: list[tuple[str, str, str, str]] = [(f"{SITE_ORIGIN}/blog", now, "weekly", "0.6")]
    for slug, post in posts.items():
        lm = post.get("date") or now
        urls.append((f"{SITE_ORIGIN}/blog/{slug}", lm, "monthly", "0.5"))
    header = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    return "\n".join(header + [_url_entries(urls), "</urlset>"])


def not_found_html() -> str:
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>404 — nie znaleziono | KupujPL Gry</title>
<meta name="robots" content="noindex, follow">
<style>{_base_styles()}
  body{{text-align:center;padding-top:8vh}}
  .code404{{font-size:96px;font-weight:800;color:#2563eb;margin:0;line-height:1}}
  .sub404{{font-size:20px;margin:8px 0 24px}}
  .links404 a{{display:inline-block;margin:6px 8px;color:#2563eb;text-decoration:none;font-weight:600}}
</style></head>
<body>
<p class="code404">404</p>
<p class="sub404">Ups! Nie znaleźliśmy tej strony.</p>
<p class="muted">Gra mogła zostać usunięta z katalogu albo link jest nieaktualny.</p>
<p><a class="cta" href="{SITE_ORIGIN}/">← Wróć do porównywarki cen</a></p>
<div class="links404">
  <a href="{SITE_ORIGIN}/">Katalog gier</a> ·
  <a href="{SITE_ORIGIN}/najwieksze-okazje">Największe okazje</a> ·
  <a href="{SITE_ORIGIN}/blog">Blog</a> ·
  <a href="{SITE_ORIGIN}/o-nas">O nas</a>
</div>
</body></html>"""


def home_website_schema_json() -> str:
    return json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": "KupujPL Gry",
            "url": SITE_ORIGIN + "/",
            "potentialAction": {
                "@type": "SearchAction",
                "target": f"{SITE_ORIGIN}/?q={{search_term_string}}",
                "query-input": "required name=search_term_string",
            },
        },
        ensure_ascii=False,
    )


def _faq_schema(title: str, slug: str, best_price: float | None, shop: str | None) -> str:
    price_a = f"{best_price:.2f} zł w {shop}" if best_price and shop else "sprawdź aktualne oferty na stronie"
    faqs = [
        ("Gdzie najtaniej kupić " + title + "?", f"Najniższa cena to obecnie {price_a}."),
        ("Czy klucze z keyshopów są legalne?", "Tak, jeśli pochodzą z autoryzowanych resellerów. Unikaj podejrzanie tanich ofert."),
        ("Jak porównać ceny?", "Użyj tabeli ofert poniżej lub pełnego porównania w aplikacji KupujPL."),
        ("Czy mogę dostać alert o spadku ceny?", "Tak — zaloguj się, śledź grę i włącz alert e-mail lub Telegram."),
        ("Czy ceny są w PLN?", "Tak, porównujemy ceny w złotówkach polskich."),
    ]
    entities = [
        {
            "@type": "Question",
            "name": q,
            "acceptedAnswer": {"@type": "Answer", "text": a},
        }
        for q, a in faqs
    ]
    return json.dumps({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entities}, ensure_ascii=False)


def _clip_text(text: str, limit: int) -> str:
    """Collapse whitespace and truncate at a word boundary with an ellipsis."""
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    cut = collapsed[: limit - 1].rstrip()
    if " " in cut:
        cut = cut[: cut.rfind(" ")].rstrip()
    return cut + "…"


def _base_styles() -> str:
    return """
    *{box-sizing:border-box}
    body{font-family:system-ui,sans-serif;line-height:1.5;color:#111;max-width:960px;margin:0 auto;padding:16px}
    .seo-header{display:flex;gap:16px;align-items:flex-start;margin-bottom:24px}
    .seo-header img{width:120px;border-radius:8px}
    table{width:100%;border-collapse:collapse;margin:16px 0}
    th,td{border:1px solid #ddd;padding:8px;text-align:left}
    th{background:#f5f5f5}
    .cta{display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600;margin:16px 0}
    .badge{display:inline-block;background:#ecfdf5;color:#065f46;padding:2px 8px;border-radius:4px;font-size:12px}
    .muted{color:#666;font-size:14px}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:12px}
    .card{border:1px solid #eee;border-radius:8px;padding:8px;display:block;text-decoration:none;color:inherit}
    @media(max-width:600px){
      .seo-header{flex-direction:column;align-items:center;text-align:center}
      .seo-header img{width:96px}
      /* Stacked, label-per-cell tables so price rows are readable on phones */
      table.offers-table,table.history-table{border:0;margin:12px 0}
      table.offers-table thead,table.history-table thead{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
      table.offers-table tr,table.history-table tr{display:block;border:1px solid #ddd;border-radius:8px;margin-bottom:10px;padding:6px 10px}
      table.offers-table td,table.history-table td{display:flex;justify-content:space-between;gap:12px;border:0;border-bottom:1px solid #f0f0f0;padding:8px 0;text-align:right}
      table.offers-table td:last-child,table.history-table td:last-child{border-bottom:0}
      table.offers-table td::before,table.history-table td::before{content:attr(data-label);font-weight:600;color:#555;text-align:left}
    }
    """


def game_landing_html(
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
    indexable: bool = True,
) -> str:
    page_url = _game_page_url(slug)
    spa_url = _spa_game_url(slug)
    safe_title = html.escape(title)
    robots = "index, follow" if indexable else "noindex, follow"

    # Unique, price-focused meta description (better search snippets than the
    # generic title). Kept ~<=160 chars so Google does not truncate it.
    if best_price_pln is not None and best_shop_name:
        meta_parts = [f"{title} na PC od {best_price_pln:.2f} zł ({best_shop_name})."]
        if savings_pln and savings_pct:
            meta_parts.append(f"Oszczędź {savings_pct}% vs Steam.")
        meta_parts.append("Porównaj ceny: Steam, GOG, Epic i sklepy z kluczami. Historia cen i alerty.")
        meta_plain = " ".join(meta_parts)
    else:
        meta_plain = (
            f"Porównaj ceny {title} na PC — Steam, GOG, Epic i sklepy z kluczami. "
            "Aktualne oferty, historia cen i alerty cenowe."
        )
    meta_plain = _clip_text(meta_plain, 160)
    meta_desc = html.escape(meta_plain)
    img = html.escape(cover_image or f"{SITE_ORIGIN}/static/favicon.ico")

    about_html = ""
    real_desc = (description or "").strip()
    if real_desc:
        about_html = f"<h2>O grze</h2><p>{html.escape(_clip_text(real_desc, 700))}</p>"

    savings_html = ""
    if savings_pln and savings_pct:
        savings_html = f'<p class="badge">Oszczędzasz {savings_pln:.2f} zł (−{savings_pct}%) vs Steam ({steam_price_pln:.2f} zł)</p>'

    history_html = ""
    if history:
        recent = history[-7:]
        rows = "".join(
            f'<tr><td data-label="Dzień">{html.escape(p["date"])}</td>'
            f'<td data-label="Najniższa">{p["best_price_pln"]:.2f} zł</td></tr>'
            for p in recent
        )
        history_html = (
            "<h2>Historia cen (ostatnie dni)</h2>"
            '<table class="history-table"><thead><tr><th>Dzień</th><th>Najniższa</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )
        if lowest_ever_pln:
            history_html += f'<p class="muted">Najniższa w historii: {lowest_ever_pln:.2f} zł'
            if avg_best_price_30d:
                history_html += f" · średnia 30 dni: {avg_best_price_30d:.2f} zł"
            history_html += "</p>"

    offers_html = ""
    if offers:
        rows = ""
        for o in offers:
            trust = html.escape(o.trust_label or ("Oficjalny" if o.is_official else "Marketplace"))
            refund = ""
            note = getattr(o, "refund_note_pl", None) or ""
            if note:
                refund = f'<p class="offer-refund-kupujpl"><strong>KupujPL — zwroty:</strong> {html.escape(note)}</p>'
            elif o.refund_policy_url:
                refund = f' <a href="{html.escape(o.refund_policy_url)}" rel="nofollow">Zwroty</a>'
            rows += (
                f'<tr><td data-label="Sklep">{html.escape(o.shop_name)}</td>'
                f'<td data-label="Cena">{o.price_pln:.2f} zł</td>'
                f'<td data-label="Zaufanie"><span class="badge">{trust}</span>{refund}</td></tr>'
            )
        offers_html = (
            "<h2>Oferty</h2>"
            '<table class="offers-table"><thead><tr><th>Sklep</th><th>Cena</th><th>Zaufanie</th></tr></thead>'
            f"<tbody>{rows}</tbody></table>"
        )

    offer_items: list[dict] = []
    offer_prices: list[float] = []
    for o in offers or []:
        price = getattr(o, "price_pln", None)
        if not price or price <= 0:
            continue
        offer_prices.append(float(price))
        offer_items.append(
            {
                "@type": "Offer",
                "price": f"{float(price):.2f}",
                "priceCurrency": "PLN",
                "availability": "https://schema.org/InStock",
                "url": page_url,
                "seller": {"@type": "Organization", "name": o.shop_name},
            }
        )

    low_price = min(offer_prices) if offer_prices else best_price_pln
    high_price = max(offer_prices) if offer_prices else best_price_pln
    price_valid_until = (date.today() + timedelta(days=7)).isoformat()

    product: dict = {
        "@context": "https://schema.org",
        "@type": ["Product", "VideoGame"],
        "name": title,
        "description": meta_plain,
        "url": page_url,
        "gamePlatform": "PC",
        "operatingSystem": "Windows",
    }
    if cover_image:
        product["image"] = cover_image
    if low_price:
        aggregate: dict = {
            "@type": "AggregateOffer",
            "priceCurrency": "PLN",
            "lowPrice": f"{low_price:.2f}",
            "highPrice": f"{high_price:.2f}" if high_price else f"{low_price:.2f}",
            "offerCount": len(offer_items) or 1,
            "availability": "https://schema.org/InStock",
            "url": page_url,
            "priceValidUntil": price_valid_until,
        }
        if offer_items:
            aggregate["offers"] = offer_items
        product["offers"] = aggregate
    json_ld_game = json.dumps(product, ensure_ascii=False)

    best_line = "Sprawdź aktualne oferty w tabeli powyżej."
    if best_price_pln is not None and best_shop_name:
        best_line = f"Od {best_price_pln:.2f} zł ({html.escape(best_shop_name)})."

    faq_ld = _faq_schema(title, slug, best_price_pln, best_shop_name)
    breadcrumb_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "KupujPL Gry", "item": SITE_ORIGIN + "/"},
                {"@type": "ListItem", "position": 2, "name": title, "item": page_url},
            ],
        },
        ensure_ascii=False,
    )

    return f"""<!DOCTYPE html>
<html lang="pl">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{safe_title} — cena, porównanie sklepów | KupujPL Gry</title>
  <meta name="description" content="{meta_desc}">
  <meta name="robots" content="{robots}">
  <link rel="canonical" href="{html.escape(page_url)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{safe_title} — KupujPL Gry">
  <meta property="og:description" content="{meta_desc}">
  <meta property="og:image" content="{SITE_ORIGIN}/og/gra/{slug}.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:url" content="{html.escape(page_url)}">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:image" content="{SITE_ORIGIN}/og/gra/{slug}.png">
  <style>{_base_styles()}</style>
  <script type="application/ld+json">{json_ld_game}</script>
  <script type="application/ld+json">{faq_ld}</script>
  <script type="application/ld+json">{breadcrumb_ld}</script>
</head>
<body>
  <nav><a href="{SITE_ORIGIN}/">KupujPL Gry</a> · <a href="{SITE_ORIGIN}/promocje">Promocje</a> · <a href="{html.escape(spa_url)}">Pełne porównanie (aplikacja)</a></nav>
  <header class="seo-header">
    <img src="{img}" alt="{safe_title}" width="120" height="180" loading="lazy">
    <div>
      <h1>{safe_title}</h1>
      <p>{meta_desc}</p>
      {savings_html}
      <a class="cta" href="{html.escape(spa_url)}">Otwórz pełne porównanie</a>
    </div>
  </header>
  {offers_html}
  {history_html}
  {about_html}
  <h2>FAQ</h2>
  <dl>
    <dt>Gdzie najtaniej?</dt><dd>{best_line}</dd>
    <dt>Alert cenowy</dt><dd>Zaloguj się i włącz alert — powiadomimy o spadku ceny.</dd>
  </dl>
  <p class="muted">Dane aktualizowane regularnie. Zawsze sprawdź warunki sklepu przed zakupem.</p>
</body>
</html>"""


def category_landing_html(*, category, games: list[GameListResponse]) -> str:
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
        cards += (
            f'<a class="card" href="{_game_page_url(g.slug)}">'
            f'<strong>{html.escape(g.title)}</strong><br>{price} {label}</a>'
        )
        list_items.append(
            {
                "@type": "ListItem",
                "position": i,
                "url": _game_page_url(g.slug),
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
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gry {safe_name} — ceny, porównanie sklepów PC | KupujPL Gry</title>
<meta name="description" content="{meta_desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{html.escape(page_url)}">
<meta property="og:type" content="website">
<meta property="og:title" content="Gry {safe_name} — KupujPL Gry">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="{html.escape(page_url)}">
<meta name="twitter:card" content="summary_large_image">
<style>{_base_styles()}</style>
<script type="application/ld+json">{item_list_ld}</script>
<script type="application/ld+json">{breadcrumb_ld}</script></head>
<body>
<nav><a href="{SITE_ORIGIN}/">KupujPL Gry</a> · <a href="{SITE_ORIGIN}/promocje">Promocje</a></nav>
<h1>Gry: {safe_name}</h1>
<p class="muted">Porównaj ceny gier z kategorii „{safe_name}” w polskich sklepach PC. Steam, GOG, Epic i sklepy z kluczami.</p>
<div class="grid">{cards or "<p>Brak gier w kategorii.</p>"}</div>
<a class="cta" href="{SITE_ORIGIN}/?category={html.escape(category.slug)}">Pełny katalog</a>
</body></html>"""


def deals_landing_html(
    *,
    kind: str,
    games: list[GameListResponse],
    max_price: int | None = None,
) -> str:
    titles = {
        "promocje": ("Promocje na gry PC", "promocje"),
        "okazje": ("Największe okazje vs Steam", "najwieksze-okazje"),
        "budget": (f"Gry poniżej {max_price} zł", f"gry-ponizej-{max_price}-zl"),
    }
    heading, path = titles.get(kind, ("Oferty", "promocje"))
    page_url = f"{SITE_ORIGIN}/{path}"
    cards = ""
    for g in games:
        sav = f" −{g.savings_pct}%" if g.savings_pct else ""
        price = f"{g.best_price_pln:.2f} zł" if g.best_price_pln else "—"
        cards += f'<a class="card" href="{_game_page_url(g.slug)}"><strong>{html.escape(g.title)}</strong><br>{price}{sav}</a>'
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8"><title>{html.escape(heading)} | KupujPL</title>
<link rel="canonical" href="{html.escape(page_url)}"><style>{_base_styles()}</style></head>
<body><h1>{html.escape(heading)}</h1><div class="grid">{cards or "<p>Brak gier.</p>"}</div>
<a class="cta" href="{SITE_ORIGIN}/">Wróć do katalogu</a></body></html>"""


_BLOG_OG_IMAGE = f"{SITE_ORIGIN}/og/logo.png"


def blog_index_html() -> str:
    posts = _load_blog_posts()
    cards = ""
    for slug, post in posts.items():
        cards += (
            f'<a class="post-card" href="{SITE_ORIGIN}/blog/{slug}">'
            f'<h2>{html.escape(post["title"])}</h2>'
            f'<p class="muted">{html.escape(post.get("date", ""))}</p>'
            f'<p>{html.escape(post.get("description", ""))}</p>'
            f'<span class="read">Czytaj →</span></a>'
        )
    item_list = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "ItemList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": i + 1,
                    "url": f"{SITE_ORIGIN}/blog/{slug}",
                    "name": post["title"],
                }
                for i, (slug, post) in enumerate(posts.items())
            ],
        },
        ensure_ascii=False,
    )
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Blog — poradniki o tanich grach PC | KupujPL Gry</title>
<meta name="description" content="Poradniki KupujPL: jak kupować gry taniej, Steam vs keyshopy, gdzie kupić klucz Steam i jak działają alerty cenowe.">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{SITE_ORIGIN}/blog">
<meta property="og:type" content="website">
<meta property="og:title" content="Blog — poradniki o tanich grach PC | KupujPL Gry">
<meta property="og:description" content="Poradniki KupujPL: jak kupować gry taniej i bezpieczniej.">
<meta property="og:image" content="{_BLOG_OG_IMAGE}">
<meta property="og:url" content="{SITE_ORIGIN}/blog">
<style>{_base_styles()}{_blog_styles()}</style>
<script type="application/ld+json">{item_list}</script></head>
<body>
<nav class="crumbs"><a href="{SITE_ORIGIN}/">KupujPL Gry</a> · <span>Blog</span></nav>
<h1>Blog KupujPL</h1>
<p class="muted">Poradniki o tańszym i bezpiecznym kupowaniu gier PC.</p>
<div class="post-list">{cards}</div>
<p style="margin-top:24px"><a class="cta" href="{SITE_ORIGIN}/">Przejdź do porównywarki</a></p>
</body></html>"""


def blog_landing_html(slug: str) -> str | None:
    posts = _load_blog_posts()
    post = posts.get(slug)
    if not post:
        return None
    page_url = f"{SITE_ORIGIN}/blog/{slug}"
    date = post.get("date", "")
    related = ""
    others = [(s, p) for s, p in posts.items() if s != slug][:3]
    if others:
        links = "".join(
            f'<li><a href="{SITE_ORIGIN}/blog/{s}">{html.escape(p["title"])}</a></li>'
            for s, p in others
        )
        related = f'<h2>Zobacz też</h2><ul class="related">{links}</ul>'

    article_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Article",
            "headline": post["title"],
            "description": post.get("description", ""),
            "datePublished": date,
            "dateModified": date,
            "image": _BLOG_OG_IMAGE,
            "author": {"@type": "Organization", "name": "KupujPL Gry"},
            "publisher": {"@type": "Organization", "name": "KupujPL Gry"},
            "mainEntityOfPage": page_url,
        },
        ensure_ascii=False,
    )
    breadcrumb_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "KupujPL Gry", "item": SITE_ORIGIN + "/"},
                {"@type": "ListItem", "position": 2, "name": "Blog", "item": SITE_ORIGIN + "/blog"},
                {"@type": "ListItem", "position": 3, "name": post["title"], "item": page_url},
            ],
        },
        ensure_ascii=False,
    )
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(post["title"])} | KupujPL Blog</title>
<meta name="description" content="{html.escape(post.get("description", ""))}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{html.escape(page_url)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{html.escape(post["title"])}">
<meta property="og:description" content="{html.escape(post.get("description", ""))}">
<meta property="og:image" content="{_BLOG_OG_IMAGE}">
<meta property="og:url" content="{html.escape(page_url)}">
<meta property="article:published_time" content="{html.escape(date)}">
<style>{_base_styles()}{_blog_styles()}</style>
<script type="application/ld+json">{article_ld}</script>
<script type="application/ld+json">{breadcrumb_ld}</script></head>
<body>
<nav class="crumbs"><a href="{SITE_ORIGIN}/">KupujPL Gry</a> · <a href="{SITE_ORIGIN}/blog">Blog</a> · <span>{html.escape(post["title"])}</span></nav>
<article><h1>{html.escape(post["title"])}</h1>
<p class="muted">{html.escape(date)}</p>
{post.get("body_html", "")}</article>
{related}
<p style="margin-top:24px"><a class="cta" href="{SITE_ORIGIN}/">Porównaj ceny gier</a> · <a href="{SITE_ORIGIN}/blog">← Wszystkie artykuły</a></p>
</body></html>"""


def _blog_styles() -> str:
    return """
    .crumbs{font-size:13px;color:#666;margin-bottom:12px}
    .crumbs a{color:#2563eb;text-decoration:none}
    .post-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
    .post-card{display:block;border:1px solid #e5e7eb;border-radius:10px;padding:16px;text-decoration:none;color:#111;transition:box-shadow .15s}
    .post-card:hover{box-shadow:0 6px 20px rgba(0,0,0,.08)}
    .post-card h2{margin:0 0 4px;font-size:18px}
    .post-card .read{color:#2563eb;font-weight:600;font-size:14px}
    .related{padding-left:18px}
    .related a{color:#2563eb}
    article h2{margin-top:22px}
    """


def price_history_landing_html(
    *,
    title: str,
    slug: str,
    cover_image: str | None,
    history: list[dict],
    lowest_ever_pln: float | None,
    avg_best_price_30d: float | None,
    best_price_pln: float | None,
) -> str:
    page_url = f"{SITE_ORIGIN}/historia-cen/{slug}"
    rows = "".join(
        f"<tr><td>{html.escape(p['date'])}</td><td>{p['best_price_pln']:.2f} zł</td></tr>"
        for p in history[-60:]
    )
    best_txt = f"{best_price_pln:.2f} zł" if best_price_pln is not None else "—"
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<title>Historia cen {html.escape(title)} | KupujPL</title>
<link rel="canonical" href="{html.escape(page_url)}"><style>{_base_styles()}</style></head>
<body><h1>Historia cen: {html.escape(title)}</h1>
<p>Obecnie od {best_txt} · najniższa {lowest_ever_pln or "—"} zł · średnia 30d {avg_best_price_30d or "—"} zł</p>
<table><tr><th>Dzień</th><th>Najniższa cena</th></tr>{rows}</table>
<a class="cta" href="{_game_page_url(slug)}">Porównaj oferty</a></body></html>"""
