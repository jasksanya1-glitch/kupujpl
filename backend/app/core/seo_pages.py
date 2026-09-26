"""SEO: sitemap, robots, SSR landing pages, blog."""
from __future__ import annotations

import html
import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.catalog_cache import catalog_generation, on_catalog_change
from app.core.game_offer_selection import (
    SITEMAP_SHOPPING_REGION,
    best_offers_map,
    iter_games_with_slugs,
)
from app.core.html_sanitize import sanitize_article_html
from app.core.json_ld_safe import absolute_public_asset_url, ensure_valid_json_ld
from app.core.site_config import SITE_ORIGIN
from app.models.models import Offer
from app.schemas.schemas import GameListResponse, OfferResponse

_BLOG = Path(__file__).resolve().parent.parent / "data" / "blog_posts.json"

# Live sitemap uses seo_landings registry + MIN_SEO_GAMES gate.
DEAL_URLS = [
    ("promocje", "Promocje na gry PC"),
    ("najwieksze-okazje", "Największe okazje vs Steam"),
    ("gry-pc-do-10-zl", "Gry PC do 10 zł"),
    ("gry-pc-do-20-zl", "Gry PC do 20 zł"),
    ("gry-pc-do-30-zl", "Gry PC do 30 zł"),
    ("gry-pc-do-50-zl", "Gry PC do 50 zł"),
    ("gry-pc-do-100-zl", "Gry PC do 100 zł"),
    ("gry-pc-znizka-50", "Gry PC −50% vs Steam"),
    ("gry-pc-znizka-70", "Gry PC −70% vs Steam"),
    ("gry-pc-znizka-80", "Gry PC −80% vs Steam"),
    ("gry-pc-znizka-90", "Gry PC −90% vs Steam"),
    ("gry-rpg", "Gry RPG PC"),
    ("gry-strategie", "Gry strategiczne PC"),
    ("gry-co-op", "Gry co-op PC"),
    ("najtansze-gry-steam", "Najtańsze gry Steam"),
    ("gry-steam-tanio", "Gry Steam tanio"),
    ("gdzie-kupic-gry-pc-najtaniej", "Gdzie kupić gry PC najtaniej"),
    ("gry-z-polskim-dubbingiem", "Gry z polskim dubbingiem"),
    ("igry-z-polskim-dublyazhem", "Ігри з польським дубляжем"),
    ("darmowe-gry", "Darmowe gry PC — Steam i Epic"),
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
    # Paths are host-root (/games/...) because public robots is served via kupujpl.pl.
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /games/\n"
        "Allow: /games/gra/\n"
        "Disallow: /panel\n"
        "Disallow: /panel3\n"
        "Disallow: /api/\n"
        "Disallow: /games/panel\n"
        "Disallow: /games/panel3\n"
        "Disallow: /games/api/\n"
        f"Sitemap: {SITE_ORIGIN}/sitemap.xml\n"
    )


SITEMAP_URL_LIMIT = 50_000
SITEMAP_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
GAME_SITEMAP_BATCH_SIZE = 500
SITEMAP_CACHE_TTL_SEC = float(os.environ.get("SITEMAP_CACHE_TTL", "90"))
_URLSET_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
)
_URLSET_FOOTER = "</urlset>"
_URLSET_OVERHEAD_BYTES = len(_URLSET_HEADER.encode("utf-8")) + len(_URLSET_FOOTER.encode("utf-8"))

_sitemap_cache_lock = threading.Lock()
_sitemap_cache_generation: int | None = None
_sitemap_cache_shards: list[str] = []
_sitemap_cache_lastmod = ""
_sitemap_cache_built_at = 0.0

SitemapUrl = tuple[str, str, str, str]


def _url_entries(urls: list[SitemapUrl]) -> str:
    parts: list[str] = []
    for loc, lastmod, changefreq, priority in urls:
        parts.append(
            f"  <url><loc>{xml_escape(loc)}</loc><lastmod>{lastmod}</lastmod>"
            f"<changefreq>{changefreq}</changefreq><priority>{priority}</priority></url>"
        )
    return "\n".join(parts)


def _urlset_xml(urls: list[SitemapUrl]) -> str:
    body = _url_entries(urls)
    if body:
        return _URLSET_HEADER + body + "\n" + _URLSET_FOOTER
    return _URLSET_HEADER + _URLSET_FOOTER


class SitemapEntryTooLargeError(ValueError):
    """A single sitemap URL cannot fit in one uncompressed sitemap file."""


def pack_sitemap_url_shards(
    urls: list[SitemapUrl],
    *,
    url_limit: int = SITEMAP_URL_LIMIT,
    max_bytes: int = SITEMAP_MAX_UNCOMPRESSED_BYTES,
) -> list[list[SitemapUrl]]:
    """Split URL entries so each shard stays within sitemap size limits."""
    if url_limit < 1:
        raise ValueError("url_limit must be at least 1")
    shards: list[list[SitemapUrl]] = []
    current: list[SitemapUrl] = []
    current_bytes = _URLSET_OVERHEAD_BYTES
    for entry in urls:
        line = _url_entries([entry]) + "\n"
        line_bytes = len(line.encode("utf-8"))
        wrapped_bytes = _URLSET_OVERHEAD_BYTES + line_bytes
        if wrapped_bytes > max_bytes:
            loc = entry[0]
            raise SitemapEntryTooLargeError(
                "Single sitemap entry does not fit in one uncompressed sitemap file: "
                f"{loc!r} is {wrapped_bytes} bytes with XML wrapper, "
                f"limit is {max_bytes} bytes."
            )
        over_count = len(current) >= url_limit
        over_bytes = current and (current_bytes + line_bytes > max_bytes)
        if current and (over_count or over_bytes):
            shards.append(current)
            current = []
            current_bytes = _URLSET_OVERHEAD_BYTES
        current.append(entry)
        current_bytes += line_bytes
    if current:
        shards.append(current)
    if not shards:
        shards.append([])
    return shards


def _homepage_entry(now: str) -> SitemapUrl:
    return (f"{SITE_ORIGIN}/", now, "daily", "1.0")


def iter_indexable_game_sitemap_urls(
    db: Session,
    *,
    region: str = SITEMAP_SHOPPING_REGION,
    batch_size: int = GAME_SITEMAP_BATCH_SIZE,
    now: str | None = None,
) -> list[SitemapUrl]:
    """Canonical /gra/{slug} URLs that share SSR best-offer eligibility. Read-only."""
    today = now or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls: list[SitemapUrl] = []
    for games in iter_games_with_slugs(db, batch_size=batch_size):
        games_by_id = {g.id: g for g in games}
        ids = [g.id for g in games]
        best = best_offers_map(db, ids, region=region, games=games_by_id)
        indexable_ids = [gid for gid in ids if gid in best]
        lastmod_by_id: dict[int, datetime | None] = {}
        if indexable_ids:
            lastmod_rows = (
                db.query(Offer.game_id, func.max(Offer.updated_at))
                .filter(Offer.game_id.in_(indexable_ids))
                .group_by(Offer.game_id)
                .all()
            )
            lastmod_by_id = {gid: lm for gid, lm in lastmod_rows}
        for game in games:
            if game.id not in best:
                continue
            lastmod = lastmod_by_id.get(game.id)
            lm = lastmod.strftime("%Y-%m-%d") if lastmod else today
            urls.append((_game_page_url(game.slug), lm, "weekly", "0.7"))
    return urls


def _build_game_sitemap_shards(db: Session) -> list[str]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = [_homepage_entry(now), *iter_indexable_game_sitemap_urls(db, now=now)]
    packed = pack_sitemap_url_shards(urls)
    return [_urlset_xml(shard) for shard in packed]


def clear_game_sitemap_cache() -> None:
    global _sitemap_cache_generation, _sitemap_cache_shards, _sitemap_cache_lastmod
    global _sitemap_cache_built_at
    with _sitemap_cache_lock:
        _sitemap_cache_generation = None
        _sitemap_cache_shards = []
        _sitemap_cache_lastmod = ""
        _sitemap_cache_built_at = 0.0


on_catalog_change(clear_game_sitemap_cache)


def game_sitemap_shards(db: Session) -> tuple[list[str], str]:
    global _sitemap_cache_generation, _sitemap_cache_shards, _sitemap_cache_lastmod
    global _sitemap_cache_built_at
    gen = catalog_generation()
    now_ts = time.time()
    with _sitemap_cache_lock:
        cache_fresh = (
            _sitemap_cache_generation == gen
            and _sitemap_cache_shards
            and (now_ts - _sitemap_cache_built_at) < SITEMAP_CACHE_TTL_SEC
        )
        if cache_fresh:
            return list(_sitemap_cache_shards), _sitemap_cache_lastmod
    shards = _build_game_sitemap_shards(db)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    with _sitemap_cache_lock:
        _sitemap_cache_generation = gen
        _sitemap_cache_shards = list(shards)
        _sitemap_cache_lastmod = now
        _sitemap_cache_built_at = time.time()
        return list(_sitemap_cache_shards), _sitemap_cache_lastmod


def sitemap_index_xml(db: Session | None = None) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    game_locs: list[str] = [f"{SITE_ORIGIN}/sitemap-games-1.xml"]
    if db is not None:
        shards, now = game_sitemap_shards(db)
        game_locs = [
            f"{SITE_ORIGIN}/sitemap-games-{idx}.xml" for idx in range(1, len(shards) + 1)
        ]
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for loc in game_locs:
        parts.append(
            f"  <sitemap><loc>{xml_escape(loc)}</loc><lastmod>{now}</lastmod></sitemap>"
        )
    parts.extend(
        [
            f"  <sitemap><loc>{xml_escape(SITE_ORIGIN)}/sitemap-categories.xml</loc><lastmod>{now}</lastmod></sitemap>",
            f"  <sitemap><loc>{xml_escape(SITE_ORIGIN)}/sitemap-deals.xml</loc><lastmod>{now}</lastmod></sitemap>",
            f"  <sitemap><loc>{xml_escape(SITE_ORIGIN)}/sitemap-blog.xml</loc><lastmod>{now}</lastmod></sitemap>",
            f"  <sitemap><loc>{xml_escape(SITE_ORIGIN)}/sitemap-news.xml</loc><lastmod>{now}</lastmod></sitemap>",
            "</sitemapindex>",
        ]
    )
    return "\n".join(parts)


def sitemap_games_xml(db: Session, *, limit: int | None = None) -> str:
    """Compatibility alias for the first numbered game sitemap shard."""
    del limit
    shards, _lastmod = game_sitemap_shards(db)
    return shards[0]


def sitemap_games_shard_xml(db: Session, shard: int) -> str | None:
    if shard < 1:
        return None
    shards, _lastmod = game_sitemap_shards(db)
    if shard > len(shards):
        return None
    return shards[shard - 1]


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
    """Only indexable landings (min game count) enter the deals sitemap."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    paths: list[str] = []
    try:
        from app.core.seo_landings import SEO_LANDINGS, estimate_landing_count, is_indexable_count
        from app.schemas.schemas import GameListResponse

        def _build(game, best, steam=None):
            from app.core.seo_landings import _savings_pct

            pct = _savings_pct(best, steam)
            steam_pln = float(steam.price_pln) if steam and steam.price_pln else None
            best_pln = float(best.price_pln) if best and best.price_pln else None
            savings = None
            if steam_pln and best_pln and best_pln < steam_pln:
                savings = round(steam_pln - best_pln, 2)
            return GameListResponse(
                id=game.id,
                title=game.title,
                slug=game.slug,
                cover_image=game.cover_image,
                steam_appid=getattr(game, "steam_appid", None),
                release_date=getattr(game, "release_date", None),
                rating=getattr(game, "rating", None),
                best_price_pln=best_pln,
                best_price_is_official=getattr(best, "is_official", None) if best else None,
                best_shop_name=getattr(best, "shop_name", None) if best else None,
                steam_price_pln=steam_pln,
                savings_pln=savings,
                savings_pct=pct,
            )

        for landing in SEO_LANDINGS:
            if landing.kind == "dubbing_uk":
                continue
            n = estimate_landing_count(db, landing, build_item=_build)
            if is_indexable_count(n):
                paths.append(landing.slug)
                if landing.slug == "gry-z-polskim-dubbingiem":
                    paths.append("igry-z-polskim-dublyazhem")
    except Exception:
        paths = [path for path, _ in DEAL_URLS]
    urls = [(f"{SITE_ORIGIN}/{path}", now, "daily", "0.8") for path in paths]
    header = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    return "\n".join(header + [_url_entries(urls), "</urlset>"])


def sitemap_blog_xml(db: Session | None = None) -> str:
    """Published articles only; lastmod from date_modified (not request time)."""
    from app.core.articles import list_published_articles
    from app.core.database import SessionLocal
    from app.models.models import Article

    own = False
    if db is None:
        db = SessionLocal()
        own = True
    try:
        arts = list_published_articles(db, limit=5000)
        urls: list[tuple[str, str, str, str]] = []
        # Index lastmod = newest article modified
        index_lm = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if arts:
            newest = max(
                (a.date_modified or a.date_published or a.date_created for a in arts),
                default=None,
            )
            if newest:
                index_lm = newest.strftime("%Y-%m-%d")
        urls.append((f"{SITE_ORIGIN}/blog", index_lm, "daily", "0.7"))
        for art in arts:
            lm_dt = art.date_modified or art.date_published or art.date_created
            lm = lm_dt.strftime("%Y-%m-%d") if lm_dt else index_lm
            urls.append((f"{SITE_ORIGIN}/blog/{art.slug}", lm, "weekly", "0.6"))
        # Fallback to JSON if DB empty (pre-migration)
        if len(urls) <= 1:
            posts = _load_blog_posts()
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for slug, post in posts.items():
                lm = post.get("date") or now
                urls.append((f"{SITE_ORIGIN}/blog/{slug}", lm, "monthly", "0.5"))
    finally:
        if own:
            db.close()
    header = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    return "\n".join(header + [_url_entries(urls), "</urlset>"])


def sitemap_news_xml(db: Session | None = None) -> str:
    """Google News sitemap — articles published in the last 2 days only."""
    return _sitemap_news_xml_impl(db, own=False)


def _sitemap_news_xml_impl(db: Session | None, own: bool = False) -> str:
    from app.core.database import SessionLocal
    from app.models.models import Article

    close = False
    if db is None:
        db = SessionLocal()
        close = True
    cutoff = datetime.utcnow() - timedelta(days=2)
    try:
        arts = (
            db.query(Article)
            .filter(
                Article.status == "published",
                Article.date_published.isnot(None),
                Article.date_published >= cutoff,
            )
            .order_by(Article.date_published.desc())
            .limit(1000)
            .all()
        )
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
            'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">',
        ]
        for art in arts:
            pub = art.date_published or art.date_created
            pub_iso = pub.strftime("%Y-%m-%dT%H:%M:%SZ") if pub else ""
            loc = f"{SITE_ORIGIN}/blog/{art.slug}"
            parts.append("  <url>")
            parts.append(f"    <loc>{xml_escape(loc)}</loc>")
            parts.append("    <news:news>")
            parts.append("      <news:publication>")
            parts.append("        <news:name>KupujPL Games</news:name>")
            parts.append("        <news:language>pl</news:language>")
            parts.append("      </news:publication>")
            parts.append(f"      <news:publication_date>{pub_iso}</news:publication_date>")
            parts.append(f"      <news:title>{xml_escape(art.title)}</news:title>")
            parts.append("    </news:news>")
            parts.append("  </url>")
        parts.append("</urlset>")
        return "\n".join(parts)
    finally:
        if close:
            db.close()


def blog_rss_xml(db: Session | None = None) -> str:
    from email.utils import format_datetime

    from app.core.articles import list_published_articles
    from app.core.database import SessionLocal

    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        arts = list_published_articles(db, limit=50)
        items = []
        for art in arts:
            link = f"{SITE_ORIGIN}/blog/{art.slug}"
            pub = art.date_published or art.date_created or datetime.utcnow()
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=timezone.utc)
            desc = html.escape(art.excerpt or art.lead or art.seo_description or "")
            enc = ""
            if art.featured_image or art.og_image:
                img = art.og_image or art.featured_image
                enc = f'<enclosure url="{html.escape(img)}" type="image/jpeg" />'
            items.append(
                f"<item>"
                f"<title>{html.escape(art.title)}</title>"
                f"<link>{html.escape(link)}</link>"
                f'<guid isPermaLink="true">{html.escape(link)}</guid>'
                f"<pubDate>{format_datetime(pub)}</pubDate>"
                f"<description>{desc}</description>"
                f"<author>{html.escape(art.author or 'Redakcja KupujPL Games')}</author>"
                f"{enc}"
                f"</item>"
            )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0">\n'
            "<channel>\n"
            "<title>KupujPL Games — Aktualności</title>\n"
            f"<link>{SITE_ORIGIN}/blog</link>\n"
            "<description>Aktualności, promocje i poradniki KupujPL Games</description>\n"
            "<language>pl</language>\n"
            + "\n".join(items)
            + "\n</channel>\n</rss>\n"
        )
    finally:
        if close:
            db.close()


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


def price_history_svg(
    history: list[dict] | None,
    *,
    width: int = 640,
    height: int = 240,
    title: str = "Wykres historii cen",
) -> str:
    """Crawlable inline SVG price history chart styled for KupujPL themes."""
    points = [p for p in (history or []) if p.get("best_price_pln") is not None]
    if len(points) < 2:
        return ""
    prices = [float(p["best_price_pln"]) for p in points]
    lo, hi = min(prices), max(prices)
    avg = sum(prices) / len(prices)
    span = (hi - lo) or 1.0
    pad_l, pad_r, pad_t, pad_b = 44, 14, 34, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    n = len(prices)

    def xy(i: int, price: float) -> tuple[float, float]:
        x = pad_l + plot_w * (i / (n - 1))
        y = pad_t + plot_h - ((price - lo) / span) * plot_h
        return x, y

    coords = [xy(i, price) for i, price in enumerate(prices)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area = (
        f"{pad_l:.1f},{pad_t + plot_h:.1f} "
        + poly
        + f" {pad_l + plot_w:.1f},{pad_t + plot_h:.1f}"
    )

    lo_i = prices.index(lo)
    hi_i = prices.index(hi)
    last_i = n - 1
    mid_i = n // 2

    # denser point markers: aim ~16–22 dots, always include key indices
    step = max(1, n // 18)
    mark_idx = set(range(0, n, step)) | {0, lo_i, hi_i, mid_i, last_i}
    if n >= 4:
        mark_idx.add(n // 4)
        mark_idx.add((3 * n) // 4)

    def short_date(raw: object) -> str:
        s = str(raw or "")
        if len(s) >= 10 and s[4] == "-":
            return s[5:10]  # MM-DD
        return s[:10]

    first_d = html.escape(str(points[0].get("date") or ""))
    last_d = html.escape(str(points[-1].get("date") or ""))
    mid_d = html.escape(short_date(points[mid_i].get("date")))
    first_short = html.escape(short_date(points[0].get("date")))
    last_short = html.escape(short_date(points[-1].get("date")))

    # grid + y ticks
    y_ticks = [lo, (lo + hi) / 2, hi]
    grid_parts: list[str] = []
    for price in y_ticks:
        _, y = xy(0, price)
        grid_parts.append(
            f'<line class="ph-grid" x1="{pad_l:.1f}" y1="{y:.1f}" '
            f'x2="{pad_l + plot_w:.1f}" y2="{y:.1f}"/>'
            f'<text class="ph-ytick" x="{pad_l - 6:.1f}" y="{y + 3.5:.1f}" '
            f'text-anchor="end">{price:.0f}</text>'
        )

    # average line
    _, avg_y = xy(0, avg)
    grid_parts.append(
        f'<line class="ph-avg" x1="{pad_l:.1f}" y1="{avg_y:.1f}" '
        f'x2="{pad_l + plot_w:.1f}" y2="{avg_y:.1f}"/>'
        f'<text class="ph-avg-label" x="{pad_l + 4:.1f}" y="{avg_y - 4:.1f}" '
        f'text-anchor="start">śr. {avg:.0f} zł</text>'
    )

    dots: list[str] = []
    for i in sorted(mark_idx):
        x, y = coords[i]
        cls = "ph-dot"
        radius = 2.4
        if i == lo_i:
            cls += " ph-dot-low"
            radius = 3.2
        elif i == hi_i:
            cls += " ph-dot-high"
            radius = 3.2
        elif i == last_i:
            cls += " ph-dot-now"
            radius = 3.6
        dots.append(
            f'<circle class="{cls}" cx="{x:.1f}" cy="{y:.1f}" r="{radius}"/>'
        )

    # callout labels for min / max / now
    def callout(i: int, label: str, cls: str, dy: float) -> str:
        x, y = coords[i]
        anchor = "start" if i < n * 0.7 else "end"
        tx = x + (8 if anchor == "start" else -8)
        return (
            f'<g class="{cls}">'
            f'<line x1="{x:.1f}" y1="{y:.1f}" x2="{tx:.1f}" y2="{y + dy:.1f}"/>'
            f'<text x="{tx:.1f}" y="{y + dy + 3:.1f}" text-anchor="{anchor}">{label}</text>'
            f"</g>"
        )

    labels = []
    if lo_i == last_i:
        labels.append(callout(last_i, f"min/teraz {lo:.0f} zł", "ph-callout ph-callout-low", 16))
    elif lo_i != hi_i:
        labels.append(callout(lo_i, f"min {lo:.0f} zł", "ph-callout ph-callout-low", -14))
    if hi_i == last_i:
        labels.append(callout(last_i, f"max/teraz {hi:.0f} zł", "ph-callout ph-callout-high", -14))
    else:
        hi_dy = 16 if hi_i != 0 else -14
        now_dy = -14
        if abs(hi_i - last_i) <= max(2, n // 12):
            hi_dy = 16
            now_dy = -16
        labels.append(callout(hi_i, f"max {hi:.0f} zł", "ph-callout ph-callout-high", hi_dy))
        if lo_i != last_i:
            labels.append(callout(last_i, f"teraz {prices[-1]:.0f} zł", "ph-callout ph-callout-now", now_dy))

    # x-axis date ticks
    x_labels = [
        (0, first_short, "start"),
        (mid_i, mid_d, "middle"),
        (last_i, last_short, "end"),
    ]
    x_parts: list[str] = []
    for i, text, anchor in x_labels:
        x, _ = coords[i]
        x_parts.append(
            f'<line class="ph-xtick" x1="{x:.1f}" y1="{pad_t + plot_h:.1f}" '
            f'x2="{x:.1f}" y2="{pad_t + plot_h + 5:.1f}"/>'
            f'<text class="ph-xlabel" x="{x:.1f}" y="{height - 8}" text-anchor="{anchor}">{text}</text>'
        )

    legend = (
        '<div class="ph-legend">'
        '<span class="ph-leg ph-leg-low">min</span>'
        '<span class="ph-leg ph-leg-avg">średnia</span>'
        '<span class="ph-leg ph-leg-high">max</span>'
        '<span class="ph-leg ph-leg-now">teraz</span>'
        "</div>"
    )

    return (
        f'<figure class="price-chart price-chart--site" role="img" aria-label="{html.escape(title)}">'
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">'
        f"<style>"
        ".price-chart--site svg{display:block;width:100%;height:auto;border-radius:0;"
        "background:var(--cp-black,#080808);border:1px solid color-mix(in srgb,var(--cp-yellow,#fcee09) 35%,transparent)}"
        ".ph-bg{fill:var(--cp-black,#080808)}"
        ".ph-area{fill:color-mix(in srgb,var(--cp-cyan,#00f0ff) 22%,transparent)}"
        ".ph-line{fill:none;stroke:var(--cp-cyan,#00f0ff);stroke-width:2.6;stroke-linejoin:round;stroke-linecap:round}"
        ".ph-grid{stroke:color-mix(in srgb,var(--cp-white,#f8f6dc) 14%,transparent);stroke-width:1}"
        ".ph-avg{stroke:var(--cp-yellow,#fcee09);stroke-width:1.4;stroke-dasharray:5 4;opacity:.9}"
        ".ph-avg-label{fill:var(--cp-yellow,#fcee09);font-size:9px;font-family:var(--font,system-ui,sans-serif)}"
        ".ph-ytick,.ph-xlabel{fill:var(--cp-white,#f8f6dc);font-size:9px;opacity:.85;"
        "font-family:var(--font,system-ui,sans-serif)}"
        ".ph-xtick{stroke:color-mix(in srgb,var(--cp-white,#f8f6dc) 35%,transparent);stroke-width:1}"
        ".ph-dot{fill:var(--cp-black,#080808);stroke:var(--cp-cyan,#00f0ff);stroke-width:1.6}"
        ".ph-dot-low{stroke:var(--cp-cyan,#00f0ff);fill:var(--cp-cyan,#00f0ff)}"
        ".ph-dot-high{stroke:var(--cp-red,#ff003c);fill:var(--cp-red,#ff003c)}"
        ".ph-dot-now{stroke:var(--cp-yellow,#fcee09);fill:var(--cp-yellow,#fcee09)}"
        ".ph-callout line{stroke:currentColor;stroke-width:1;opacity:.7}"
        ".ph-callout text{font-size:9px;font-family:var(--font,system-ui,sans-serif);font-weight:700}"
        ".ph-callout-low{color:var(--cp-cyan,#00f0ff);fill:var(--cp-cyan,#00f0ff)}"
        ".ph-callout-high{color:var(--cp-red,#ff003c);fill:var(--cp-red,#ff003c)}"
        ".ph-callout-now{color:var(--cp-yellow,#fcee09);fill:var(--cp-yellow,#fcee09)}"
        "</style>"
        f'<rect class="ph-bg" width="{width}" height="{height}"/>'
        f"{''.join(grid_parts)}"
        f'<polygon class="ph-area" points="{area}"/>'
        f'<polyline class="ph-line" points="{poly}"/>'
        f"{''.join(dots)}"
        f"{''.join(labels)}"
        f"{''.join(x_parts)}"
        "</svg>"
        f"{legend}"
        f'<figcaption class="muted ph-caption">{first_d} → {last_d} · '
        f"najniższa {lo:.2f} zł · najwyższa {hi:.2f} zł · średnia {avg:.2f} zł</figcaption></figure>"
    )



def _collection_cards(games: list[GameListResponse]) -> tuple[str, list[dict]]:
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



def _faq_page_schema(pairs: list[tuple[str, str]]) -> str:
    entities = [
        {
            "@type": "Question",
            "name": q,
            "acceptedAnswer": {"@type": "Answer", "text": a},
        }
        for q, a in pairs
    ]
    return json.dumps(
        {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entities},
        ensure_ascii=False,
    )


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
    .card img{width:100%;aspect-ratio:460/215;object-fit:cover;border-radius:6px;margin-bottom:6px;display:block;background:#eee}
    .price-chart{margin:16px 0}
    .price-chart svg{display:block;border:1px solid #e5e7eb;border-radius:8px}
    .hub-links{margin:20px 0;font-size:14px}
    .hub-links a{color:#2563eb;margin-right:10px}
    .lead{font-size:17px;margin:8px 0 18px}
    .faq{margin:28px 0}
    .faq h2{font-size:20px}
    .faq details{border-bottom:1px solid #eee;padding:8px 0}
    .faq summary{cursor:pointer;font-weight:600}
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
  body.layout-split.seo-collection{{
    height:auto;min-height:100vh;overflow:auto;overflow-x:hidden;
  }}
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
  .seo-collection .faq{{margin:28px 0}}
  .seo-collection .faq h2{{font-size:1.25rem;margin-bottom:8px}}
  .seo-collection .faq details{{border-bottom:1px solid color-mix(in srgb, var(--text,#e8e6e3) 12%, transparent);padding:8px 0}}
  .seo-collection .faq summary{{cursor:pointer;font-weight:600}}
  .seo-collection .hub-links{{margin:12px 0 8px;font-size:.9rem;opacity:.85}}
  .seo-collection .hub-links a{{color:inherit;margin-right:12px;text-decoration:underline}}
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



def deals_landing_html(
    *,
    kind: str,
    games: list[GameListResponse],
    max_price: int | None = None,
    path_override: str | None = None,
    heading_override: str | None = None,
    indexable: bool = True,
    min_savings_pct: int | None = None,
    hub_html: str | None = None,
) -> str:
    titles = {
        "promocje": ("Promocje na gry PC", "promocje"),
        "okazje": ("Największe okazje vs Steam", "najwieksze-okazje"),
        "budget": (f"Gry PC do {max_price} zł", f"gry-pc-do-{max_price}-zl"),
        "discount": (
            f"Gry PC −{min_savings_pct}% vs Steam",
            f"gry-pc-znizka-{min_savings_pct}",
        ),
        "genre": ("Gry PC", "gry"),
        "intent_steam_cheap": ("Najtańsze gry Steam", "najtansze-gry-steam"),
        "intent_steam_sale": ("Gry Steam tanio", "gry-steam-tanio"),
    }
    heading, path = titles.get(kind, ("Oferty", "promocje"))
    if heading_override:
        heading = heading_override
    if path_override:
        path = path_override
    if kind == "budget" and max_price and not heading_override:
        heading = f"Gry PC do {max_price} zł"
    if kind == "budget" and max_price and not path_override:
        path = f"gry-pc-do-{max_price}-zl"

    page_url = f"{SITE_ORIGIN}/{path}"
    count = len(games)
    cheapest = min((g.best_price_pln for g in games if g.best_price_pln), default=None)
    cheap_bit = f" już od {cheapest:.2f} zł" if cheapest else ""

    if kind == "budget" and max_price == 30:
        meta_plain = _clip_text(
            f"Gry PC do 30 zł{cheap_bit} — aktualne oferty Steam, GOG, Epic i keyshopów. "
            f"Lista {count} tanich gier PC poniżej 30 złotych z porównaniem cen.",
            160,
        )
        lead = (
            "Szukasz <strong>gier PC do 30 zł</strong>? Poniżej aktualne tytuły, których "
            "najniższa cena w porównywanych sklepach nie przekracza 30 zł. Sprawdź historię "
            "cen i kup, gdy oferta jest najkorzystniejsza."
        )
        faqs = [
            (
                "Jakie gry PC kupię do 30 zł?",
                "Na tej liście są tytuły z aktualną najniższą ceną do 30 zł w sklepach "
                "porównywanych przez KupujPL (Steam, GOG, Epic i marketplace kluczy).",
            ),
            (
                "Czy ceny są w złotówkach?",
                "Tak — porównujemy ceny w PLN. Przed zakupem sprawdź region aktywacji klucza.",
            ),
            (
                "Skąd biorą się tańsze oferty?",
                "Często z promocji Steam/GOG/Epic albo z marketplace'ów kluczy. "
                "Zawsze sprawdzaj ocenę sprzedawcy i zasady zwrotów.",
            ),
        ]
    elif kind == "budget":
        meta_plain = _clip_text(
            f"Gry PC poniżej {max_price} zł{cheap_bit} — porównaj ceny w sklepach. "
            f"{count} tytułów w budżecie do {max_price} zł.",
            160,
        )
        lead = (
            f"Lista gier PC z aktualną najniższą ceną poniżej <strong>{max_price} zł</strong>. "
            "Porównujemy Steam, GOG, Epic i sklepy z kluczami."
        )
        faqs = [
            (
                f"Gdzie znaleźć gry PC poniżej {max_price} zł?",
                f"Na KupujPL filtrujemy oferty i pokazujemy tytuły do {max_price} zł "
                "z aktualnym porównaniem sklepów.",
            ),
            (
                "Czy lista jest aktualna?",
                "Tak — ceny odświeżamy regularnie; otwórz stronę gry, by zobaczyć oferty na żywo.",
            ),
        ]
    elif kind == "okazje":
        meta_plain = _clip_text(
            f"Największe okazje na gry PC vs Steam{cheap_bit}. "
            "Sprawdź, gdzie kupić taniej niż na Steam.",
            160,
        )
        lead = "Tytuły z największą różnicą względem ceny Steam — warto sprawdzić przed zakupem."
        faqs = [
            (
                "Jak liczycie okazję vs Steam?",
                "Porównujemy najniższą ofertę w katalogu z aktualną ceną Steam w PLN.",
            ),
        ]
    else:
        meta_plain = _clip_text(
            f"Promocje na gry PC{cheap_bit} — porównaj przecenione tytuły w polskich sklepach.",
            160,
        )
        lead = "Aktualne promocje na gry PC z porównaniem cen w 10 sklepach."
        faqs = [
            (
                "Czy KupujPL sprzedaje gry?",
                "Nie — jesteśmy porównywarką. Zakupu dokonujesz bezpośrednio w wybranym sklepie.",
            ),
        ]

    if kind == "discount" and min_savings_pct:
        meta_plain = _clip_text(
            f"Gry PC przecenione o co najmniej {min_savings_pct}% względem Steam{cheap_bit}. "
            f"{count} tytułów z porównaniem cen w sklepach.",
            160,
        )
        lead = (
            f"Lista gier PC, gdzie najniższa oferta jest o <strong>co najmniej {min_savings_pct}%</strong> "
            "tańsza niż aktualna cena Steam."
        )
        faqs = [
            (
                f"Jak liczycie zniżkę −{min_savings_pct}%?",
                "Porównujemy najniższą ofertę w katalogu KupujPL z aktualną ceną Steam w PLN.",
            ),
            (
                "Czy to oficjalne sklepy?",
                "Pokazujemy sklepy oficjalne i marketplace'y kluczy — sprawdzaj region aktywacji.",
            ),
        ]
    elif kind == "genre":
        meta_plain = _clip_text(
            f"{heading}{cheap_bit} — porównaj ceny w Steam, GOG, Epic i keyshopach. Lista {count} tytułów.",
            160,
        )
        lead = f"Aktualne ceny w kategorii <strong>{html.escape(heading.split('—')[0].strip())}</strong>."
        faqs = [
            (
                "Skąd biorą się kategorie?",
                "Mapujemy gatunki Steam na katalog KupujPL, potem porównujemy oferty sklepów.",
            ),
        ]
    elif kind == "intent_steam_cheap":
        meta_plain = _clip_text(
            f"Najtańsze gry Steam{cheap_bit} — aktualne oficjalne oferty Steam od najniższej ceny.",
            160,
        )
        lead = "Ranking najtańszych aktualnych ofert <strong>Steam</strong> w złotówkach."
        faqs = [
            (
                "Czy to tylko Steam?",
                "Tak — ta lista pokazuje oficjalne ceny Steam. Na stronie gry porównasz też inne sklepy.",
            ),
        ]
    elif kind == "intent_steam_sale":
        meta_plain = _clip_text(
            f"Gry Steam tanio{cheap_bit} — tytuły wyraźnie tańsze niż na Steam.",
            160,
        )
        lead = "Gry wyraźnie tańsze niż na Steam — porównanie sklepów oficjalnych i marketplace'ów."
        faqs = [
            (
                "Czym różni się to od promocji?",
                "Tu liczy się różnica względem ceny Steam, nie tylko dowolna przecena katalogowa.",
            ),
        ]

    cards, list_items = _collection_cards(games)
    item_list_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": heading,
            "url": page_url,
            "description": meta_plain,
            "mainEntity": {"@type": "ItemList", "numberOfItems": count, "itemListElement": list_items},
        },
        ensure_ascii=False,
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
    faq_ld = _faq_page_schema(faqs)
    faq_html = "".join(
        f"<details><summary>{html.escape(q)}</summary><p>{html.escape(a)}</p></details>"
        for q, a in faqs
    )
    if hub_html is None:
        try:
            from app.core.seo_landings import hub_links_html
            hub = hub_links_html(None)
        except Exception:
            hub = (
                f'<p class="hub-links">'
                f'<a href="{SITE_ORIGIN}/darmowe-gry">Darmowe gry</a>'
                f'<a href="{SITE_ORIGIN}/gry-pc-do-30-zl">Gry PC do 30 zł</a>'
                f'<a href="{SITE_ORIGIN}/gry-pc-do-20-zl">do 20 zł</a>'
                f'<a href="{SITE_ORIGIN}/gry-pc-do-50-zl">do 50 zł</a>'
                f'<a href="{SITE_ORIGIN}/gry-z-polskim-dubbingiem">Gry z polskim dubbingiem</a>'
                f'<a href="{SITE_ORIGIN}/promocje">Promocje</a>'
                f"</p>"
            )
    else:
        hub = hub_html
    robots = "index, follow" if indexable else "noindex, follow"
    og_image = f"{SITE_ORIGIN}/og/logo.png"
    safe_heading = html.escape(heading)
    meta_desc = html.escape(meta_plain)
    exact_title = kind == "budget" and max_price in (10, 20, 30, 50, 100)
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



def dubbing_landing_html(
    *,
    games: list[GameListResponse],
    lang: str = "pl",
) -> str:
    """SEO collection for Polish full-audio games (+ UA variant)."""
    if lang == "uk":
        path = "igry-z-polskim-dublyazhem"
        page_url = f"{SITE_ORIGIN}/{path}"
        heading = "Ігри з польським дубляжем"
        meta_plain = _clip_text(
            "Ігри з польським дубляжем (повне озвучення) — порівняйте ціни PC у Steam, "
            "GOG, Epic і keyshopах. Актуальний список із польським аудіо.",
            160,
        )
        lead = (
            "Підбірка <strong>ігор з польським дубляжем</strong> (повне озвучення за даними Steam). "
            "Порівнюємо ціни в PLN і показуємо, де купити дешевше."
        )
        hreflang_alt = f'{SITE_ORIGIN}/gry-z-polskim-dubbingiem'
        html_lang = "uk"
        faqs = [
            (
                "Що означає «польський дубляж»?",
                "Повне польське озвучення (full audio) згідно з даними Steam — не лише субтитри.",
            ),
            (
                "Чому ціни в злотих?",
                "KupujPL порівнює пропозиції для польського ринку в PLN.",
            ),
        ]
        cta = "До каталогу"
        related = "Gry z polskim dubbingiem (PL)"
    else:
        path = "gry-z-polskim-dubbingiem"
        page_url = f"{SITE_ORIGIN}/{path}"
        heading = "Gry z polskim dubbingiem"
        meta_plain = _clip_text(
            "Gry z polskim dubbingiem (pełne audio) — porównaj ceny PC. "
            "Lista tytułów z polskim dubbingiem wg Steam + aktualne oferty sklepów.",
            160,
        )
        lead = (
            "Szukasz <strong>gier z polskim dubbingiem</strong>? Poniżej tytuły z pełnym "
            "polskim audio (wg Steam). Porównaj ceny i historię promocji przed zakupem. "
            "Wariant UA: <em>ігри з польським дубляжем</em>."
        )
        hreflang_alt = f"{SITE_ORIGIN}/igry-z-polskim-dublyazhem"
        html_lang = "pl"
        faqs = [
            (
                "Czym jest polski dubbing w grach?",
                "Pełne polskie audio / dubbing (full audio) według Steam — nie tylko napisy/interfejs.",
            ),
            (
                "Skąd wiecie, że gra ma polskie audio?",
                "Odczytujemy pole języków Steam: język oznaczony gwiazdką (*) ma pełne audio.",
            ),
            (
                "Czy mogę zobaczyć też tańsze gry?",
                f"Tak — sprawdź też listę Gry PC do 30 zł: {SITE_ORIGIN}/gry-pc-do-30-zl",
            ),
        ]
        cta = "Wróć do katalogu"
        related = "Ігри з польським дубляжем (UA)"

    cards, list_items = _collection_cards(games)
    count = len(games)
    item_list_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": heading,
            "url": page_url,
            "description": meta_plain,
            "inLanguage": html_lang,
            "mainEntity": {"@type": "ItemList", "numberOfItems": count, "itemListElement": list_items},
        },
        ensure_ascii=False,
    )
    faq_ld = _faq_page_schema(faqs)
    faq_html = "".join(
        f"<details><summary>{html.escape(q)}</summary><p>{html.escape(a)}</p></details>"
        for q, a in faqs
    )
    safe_heading = html.escape(heading)
    meta_desc = html.escape(meta_plain)
    og_image = f"{SITE_ORIGIN}/og/logo.png"
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



def freebies_landing_html(
    *,
    current: list[dict],
    upcoming: list[dict],
    always_free: list[GameListResponse] | None = None,
) -> str:
    """SEO landing for Steam / Epic limited free giveaways."""
    path = "darmowe-gry"
    page_url = f"{SITE_ORIGIN}/{path}"
    heading = "Darmowe gry PC — Steam i Epic Games"
    n_cur = len(current)
    meta_plain = _clip_text(
        f"Darmowe gry PC — Steam i Epic Games Store. Teraz: {n_cur} aktywnych darmowych "
        "tytułów + zapowiedzi. Free to keep, free weekends i zawsze darmowe hity.",
        160,
    )

    def _cards(items: list[dict], *, upcoming_mode: bool = False) -> str:
        cards = ""
        for g in items:
            title = html.escape(g.get("title") or "")
            shop = html.escape(g.get("shop") or "")
            ends = g.get("ends_at") or g.get("starts_at") or ""
            ends_short = html.escape(str(ends)[:10]) if ends else ""
            badge = "Wkrótce" if upcoming_mode else "Za darmo teraz"
            href = g.get("slug")
            if href:
                url = _game_page_url(href)
            else:
                url = g.get("affiliate_url") or g.get("store_url") or SITE_ORIGIN + "/"
            orig = g.get("original_price_pln")
            price_bit = f" (zwykle {float(orig):.2f} zł)" if orig else ""
            when = f'<br><span class="muted">{ends_short}</span>' if ends_short else ""
            cards += (
                f'<a class="card" href="{html.escape(url)}" rel="noopener">'
                f"<strong>{title}</strong><br>{shop} · {badge}{price_bit}{when}</a>"
            )
        return cards

    always_cards = ""
    for g in always_free or []:
        always_cards += (
            f'<a class="card" href="{_game_page_url(g.slug)}">'
            f"<strong>{html.escape(g.title)}</strong><br>Zawsze za darmo</a>"
        )

    list_items = []
    for i, g in enumerate(current + upcoming, start=1):
        list_items.append(
            {
                "@type": "ListItem",
                "position": i,
                "name": g.get("title"),
                "url": (
                    _game_page_url(g["slug"])
                    if g.get("slug")
                    else (g.get("store_url") or page_url)
                ),
            }
        )
    item_list_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": heading,
            "url": page_url,
            "description": meta_plain,
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": len(list_items),
                "itemListElement": list_items,
            },
        },
        ensure_ascii=False,
    )
    faqs = [
        (
            "Gdzie są darmowe gry na Epic Games Store?",
            "Epic co tydzień oddaje gry za darmo (free to keep). Tu pokazujemy aktualne "
            "i nadchodzące tytuły z linkiem do sklepu.",
        ),
        (
            "Czy darmowe gry Steam też monitorujecie?",
            "Tak — szukamy czasowych promocji 100% i weekendów za darmo oraz pokazujemy "
            "popularne tytuły zawsze darmowe.",
        ),
        (
            "Czy muszę się rejestrować na KupujPL?",
            "Nie. Lista darmowych gier jest publiczna. Konto pomaga tylko przy alertach cen.",
        ),
    ]
    faq_ld = _faq_page_schema(faqs)
    faq_html = "".join(
        f"<details><summary>{html.escape(q)}</summary><p>{html.escape(a)}</p></details>"
        for q, a in faqs
    )
    safe_heading = html.escape(heading)
    meta_desc = html.escape(meta_plain)
    og_image = f"{SITE_ORIGIN}/og/logo.png"
    current_html = _cards(current) or (
        "<p>Brak aktywnych czasowych darmowych gier — zajrzyj do zapowiedzi.</p>"
    )
    upcoming_html = _cards(upcoming, upcoming_mode=True) or (
        "<p>Brak zapowiedzianych darmowych gier.</p>"
    )
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{safe_heading} | KupujPL Gry</title>
<meta name="description" content="{meta_desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{html.escape(page_url)}">
<meta property="og:type" content="website">
<meta property="og:title" content="{safe_heading}">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{og_image}">
<meta property="og:url" content="{html.escape(page_url)}">
<meta name="twitter:card" content="summary_large_image">
<style>{_base_styles()}</style>
<script type="application/ld+json">{item_list_ld}</script>
<script type="application/ld+json">{faq_ld}</script></head>
<body>
<nav><a href="{SITE_ORIGIN}/">KupujPL Gry</a> · <a href="{SITE_ORIGIN}/promocje">Promocje</a></nav>
<h1>{safe_heading}</h1>
<p class="lead">Na bieżąco śledzimy <strong>darmowe gry Epic Games Store</strong> (free to keep)
oraz czasowe promocje <strong>Steam</strong>. Weź zanim znikną — lista odświeża się automatycznie.</p>
<p class="hub-links">
  <a href="{SITE_ORIGIN}/gry-pc-do-30-zl">Gry PC do 30 zł</a>
  <a href="{SITE_ORIGIN}/promocje">Promocje</a>
  <a href="{SITE_ORIGIN}/gry-z-polskim-dubbingiem">Gry z polskim dubbingiem</a>
</p>
<h2>Teraz za darmo</h2>
<div class="grid">{current_html}</div>
<h2>Wkrótce za darmo</h2>
<div class="grid">{upcoming_html}</div>
<h2>Zawsze darmowe hity</h2>
<div class="grid">{always_cards or "<p>Brak danych.</p>"}</div>
<section class="faq"><h2>Najczęstsze pytania</h2>{faq_html}</section>
<a class="cta" href="{SITE_ORIGIN}/">Wróć do porównywarki</a>
</body></html>"""



_BLOG_OG_IMAGE = f"{SITE_ORIGIN}/og/logo.png"
_PUBLISHER_LOGO = f"{SITE_ORIGIN}/og/logo.png"


def _fmt_iso(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def blog_index_html(db: Session | None = None) -> str:
    from app.core.articles import list_published_articles
    from app.core.database import SessionLocal

    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        arts = list_published_articles(db, limit=100)
        if not arts:
            # Legacy JSON fallback
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
        else:
            cards = ""
            for art in arts:
                date_s = (
                    (art.date_published or art.date_created).strftime("%Y-%m-%d")
                    if (art.date_published or art.date_created)
                    else ""
                )
                excerpt = art.excerpt or art.lead or art.seo_description or ""
                cards += (
                    f'<a class="post-card" href="{SITE_ORIGIN}/blog/{art.slug}">'
                    f'<h2>{html.escape(art.title)}</h2>'
                    f'<p class="muted">{html.escape(date_s)} · {html.escape(art.author or "")}</p>'
                    f'<p>{html.escape(excerpt)}</p>'
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
                            "url": f"{SITE_ORIGIN}/blog/{art.slug}",
                            "name": art.title,
                        }
                        for i, art in enumerate(arts)
                    ],
                },
                ensure_ascii=False,
            )
        return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Aktualności i poradniki — KupujPL Games</title>
<meta name="description" content="Aktualności o promocjach na gry PC, darmowe gry i poradniki KupujPL Games.">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{SITE_ORIGIN}/blog">
<link rel="alternate" type="application/rss+xml" title="KupujPL RSS" href="{SITE_ORIGIN}/blog/feed.xml">
<meta property="og:type" content="website">
<meta property="og:title" content="Aktualności i poradniki — KupujPL Games">
<meta property="og:description" content="Promocje, darmowe gry i poradniki KupujPL.">
<meta property="og:image" content="{_BLOG_OG_IMAGE}">
<meta property="og:url" content="{SITE_ORIGIN}/blog">
<style>{_base_styles()}{_blog_styles()}</style>
<script type="application/ld+json">{item_list}</script></head>
<body>
<nav class="crumbs"><a href="{SITE_ORIGIN}/">KupujPL Games</a> · <span>Aktualności</span></nav>
<h1>Aktualności i poradniki</h1>
<p class="muted">Promocje, darmowe gry i poradniki o tańszym kupowaniu gier PC.</p>
<div class="post-list">{cards}</div>
<p style="margin-top:24px"><a class="cta" href="{SITE_ORIGIN}/">Przejdź do porównywarki</a></p>
</body></html>"""
    finally:
        if close:
            db.close()


def blog_landing_html(slug: str, db: Session | None = None, *, preview: bool = False) -> str | None:
    from app.core.articles import get_article_by_slug, list_published_articles
    from app.core.database import SessionLocal
    from app.core.price_history import lowest_ever_label_pl
    from app.models.models import Offer

    close = False
    if db is None:
        db = SessionLocal()
        close = True
    try:
        art = get_article_by_slug(db, slug, allow_unpublished=preview)
        if not art:
            # Legacy JSON
            posts = _load_blog_posts()
            post = posts.get(slug)
            if not post:
                return None
            page_url = f"{SITE_ORIGIN}/blog/{slug}"
            date = post.get("date", "")
            article_ld = ensure_valid_json_ld(
                {
                    "@context": "https://schema.org",
                    "@type": "Article",
                    "headline": post["title"],
                    "description": post.get("description", ""),
                    "datePublished": date,
                    "dateModified": date,
                    "image": _BLOG_OG_IMAGE,
                    "author": {"@type": "Organization", "name": "Redakcja KupujPL Games"},
                    "publisher": {
                        "@type": "Organization",
                        "name": "KupujPL Games",
                        "logo": {"@type": "ImageObject", "url": _PUBLISHER_LOGO},
                    },
                    "mainEntityOfPage": page_url,
                }
            )
            safe_body = sanitize_article_html(post.get("body_html", ""))
            return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(post["title"])} | KupujPL</title>
<meta name="description" content="{html.escape(post.get("description", ""))}">
<meta name="robots" content="index, follow, max-image-preview:large">
<link rel="canonical" href="{html.escape(page_url)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{html.escape(post["title"])}">
<meta property="og:description" content="{html.escape(post.get("description", ""))}">
<meta property="og:image" content="{_BLOG_OG_IMAGE}">
<meta property="og:url" content="{html.escape(page_url)}">
<meta property="article:published_time" content="{html.escape(date)}">
<style>{_base_styles()}{_blog_styles()}</style>
<script type="application/ld+json">{article_ld}</script></head>
<body>
<nav class="crumbs"><a href="{SITE_ORIGIN}/">KupujPL Games</a> · <a href="{SITE_ORIGIN}/blog">Aktualności</a> · <span>{html.escape(post["title"])}</span></nav>
<article><h1>{html.escape(post["title"])}</h1>
<p class="muted">Redakcja KupujPL Games · {html.escape(date)}</p>
{safe_body}</article>
<p style="margin-top:24px"><a class="cta" href="{SITE_ORIGIN}/">Sprawdź aktualne ceny w KupujPL Games</a></p>
</body></html>"""

        page_url = art.canonical_url or f"{SITE_ORIGIN}/blog/{art.slug}"
        is_indexable = art.status == "published" and not preview
        robots = (
            "index, follow, max-image-preview:large"
            if is_indexable
            else "noindex, follow"
        )
        title = art.seo_title or art.title
        desc = art.seo_description or art.excerpt or art.lead or ""
        og_title = art.og_title or title
        og_desc = art.og_description or desc
        og_image = absolute_public_asset_url(
            art.og_image or art.featured_image,
            fallback=_BLOG_OG_IMAGE,
        )
        pub = art.date_published or art.date_created
        mod = art.date_modified or pub
        pub_iso = _fmt_iso(pub)
        mod_iso = _fmt_iso(mod)
        author = art.author or "Redakcja KupujPL Games"
        safe_content = sanitize_article_html(art.content)

        hero = ""
        if art.featured_image:
            w = art.featured_image_width or ""
            h = art.featured_image_height or ""
            wh = f' width="{w}" height="{h}"' if w and h else ""
            alt = html.escape(art.featured_image_alt or art.title)
            hero_src = absolute_public_asset_url(art.featured_image, fallback=_BLOG_OG_IMAGE)
            # LCP: no lazy on featured
            hero = (
                f'<figure class="article-hero">'
                f'<img src="{html.escape(hero_src)}" alt="{alt}"{wh} '
                f'fetchpriority="high" decoding="async">'
                f"</figure>"
            )

        game_block = ""
        if art.game_id and art.game:
            g = art.game
            best = (
                db.query(Offer)
                .filter(Offer.game_id == g.id, Offer.in_stock.is_(True), Offer.price_pln > 0)
                .order_by(Offer.price_pln.asc())
                .first()
            )
            cur = art.price_current if art.price_current is not None else (
                best.price_pln if best else None
            )
            label = lowest_ever_label_pl(g, cur) if cur is not None else None
            # Prefer careful wording when we cannot prove market-wide historical min
            low_txt = ""
            if label:
                low_txt = f"<li>Najniższa cena zarejestrowana przez KupujPL: <strong>{html.escape(label)}</strong></li>"
            elif g.lowest_ever_pln is not None:
                low_txt = (
                    f"<li>Jedna z najniższych cen w bazie KupujPL: "
                    f"<strong>{g.lowest_ever_pln:.2f} zł</strong></li>"
                )
            disc = ""
            if art.discount_percent:
                disc = f"<li>Rabat (vs wyższa oferta w skanie): <strong>−{art.discount_percent}%</strong></li>"
            shop = html.escape(art.shop_name or (best.shop_name if best else "—"))
            price_s = f"{cur:.2f} zł" if cur is not None else "—"
            game_block = f"""
<aside class="article-game">
  <h2>Aktualna cena: {html.escape(g.title)}</h2>
  <ul>
    <li>Aktualna cena: <strong>{price_s}</strong></li>
    {low_txt}
    {disc}
    <li>Sklep: <strong>{shop}</strong></li>
  </ul>
  <a class="cta" href="{SITE_ORIGIN}/gra/{html.escape(g.slug)}">Porównaj ceny</a>
</aside>"""

        related_arts = [a for a in list_published_articles(db, limit=6) if a.slug != art.slug][:3]
        related = ""
        if related_arts:
            links = "".join(
                f'<li><a href="{SITE_ORIGIN}/blog/{a.slug}">{html.escape(a.title)}</a></li>'
                for a in related_arts
            )
            related = f'<h2>Powiązane artykuły</h2><ul class="related">{links}</ul>'

        schema_type = "NewsArticle" if art.article_type in (
            "deal", "free_game", "news", "price_drop", "release"
        ) else "Article"
        image_ld: str | dict
        if art.featured_image_width and art.featured_image_height and art.featured_image:
            image_ld = {
                "@type": "ImageObject",
                "url": absolute_public_asset_url(art.featured_image, fallback=og_image),
                "width": art.featured_image_width,
                "height": art.featured_image_height,
            }
        else:
            image_ld = og_image
        article_ld = ensure_valid_json_ld(
            {
                "@context": "https://schema.org",
                "@type": schema_type,
                "headline": art.title,
                "description": desc,
                "image": image_ld,
                "datePublished": pub_iso,
                "dateModified": mod_iso,
                "author": {"@type": "Organization", "name": author},
                "publisher": {
                    "@type": "Organization",
                    "name": "KupujPL Games",
                    "logo": {"@type": "ImageObject", "url": _PUBLISHER_LOGO},
                },
                "mainEntityOfPage": {"@type": "WebPage", "@id": page_url},
            }
        )
        breadcrumb_ld = ensure_valid_json_ld(
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "KupujPL Games", "item": SITE_ORIGIN + "/"},
                    {"@type": "ListItem", "position": 2, "name": "Aktualności", "item": SITE_ORIGIN + "/blog"},
                    {"@type": "ListItem", "position": 3, "name": art.title, "item": page_url},
                ],
            }
        )
        org_ld = ensure_valid_json_ld(
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "KupujPL Games",
                "url": SITE_ORIGIN + "/",
                "logo": _PUBLISHER_LOGO,
            }
        )
        og_wh = ""
        if art.featured_image_width and art.featured_image_height:
            og_wh = (
                f'<meta property="og:image:width" content="{art.featured_image_width}">\n'
                f'<meta property="og:image:height" content="{art.featured_image_height}">'
            )
        lead_html = f"<p class=\"lead\">{html.escape(art.lead)}</p>" if art.lead else ""
        date_label = pub.strftime("%Y-%m-%d") if pub else ""

        return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{html.escape(title)} | KupujPL Games</title>
<meta name="description" content="{html.escape(desc)}">
<meta name="robots" content="{robots}">
<link rel="canonical" href="{html.escape(page_url)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{html.escape(og_title)}">
<meta property="og:description" content="{html.escape(og_desc)}">
<meta property="og:url" content="{html.escape(page_url)}">
<meta property="og:image" content="{html.escape(og_image)}">
{og_wh}
<meta property="article:published_time" content="{html.escape(pub_iso)}">
<meta property="article:modified_time" content="{html.escape(mod_iso)}">
<style>{_base_styles()}{_blog_styles()}</style>
<script type="application/ld+json">{article_ld}</script>
<script type="application/ld+json">{breadcrumb_ld}</script>
<script type="application/ld+json">{org_ld}</script></head>
<body>
<nav class="crumbs"><a href="{SITE_ORIGIN}/">KupujPL Games</a> · <a href="{SITE_ORIGIN}/blog">Aktualności</a> · <span>{html.escape(art.title)}</span></nav>
<article>
<h1>{html.escape(art.title)}</h1>
{lead_html}
{hero}
<p class="muted"><a href="{SITE_ORIGIN}/redakcja">{html.escape(author)}</a> · {html.escape(date_label)}</p>
{safe_content}
</article>
{game_block}
{related}
<p style="margin-top:24px"><a class="cta" href="{SITE_ORIGIN}/">Sprawdź aktualne ceny w KupujPL Games</a> · <a href="{SITE_ORIGIN}/blog">← Wszystkie artykuły</a></p>
</body></html>"""
    finally:
        if close:
            db.close()


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
    .lead{font-size:1.15rem;line-height:1.45;color:#333}
    .article-hero{margin:16px 0}
    .article-hero img{width:100%;max-width:960px;height:auto;border-radius:8px;display:block}
    .article-game{margin:24px 0;padding:16px;border:1px solid #e5e7eb;border-radius:10px;background:#fafafa}
    .article-game ul{padding-left:18px}
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
    game_url = _game_page_url(slug)
    safe_title = html.escape(title)
    best_txt = f"{best_price_pln:.2f} zł" if best_price_pln is not None else "—"
    low_txt = f"{lowest_ever_pln:.2f} zł" if lowest_ever_pln is not None else "—"
    avg_txt = f"{avg_best_price_30d:.2f} zł" if avg_best_price_30d is not None else "—"
    meta_plain = _clip_text(
        f"Historia cen {title} na PC — wykres i najniższe ceny dzień po dniu. "
        f"Teraz od {best_txt}, rekord {low_txt}. Porównaj oferty sklepów.",
        160,
    )
    meta_desc = html.escape(meta_plain)
    chart = price_history_svg(history, title=f"Historia cen {title}")
    rows = "".join(
        f'<tr><td data-label="Dzień">{html.escape(p["date"])}</td>'
        f'<td data-label="Najniższa">{p["best_price_pln"]:.2f} zł</td></tr>'
        for p in history[-60:]
    )
    img = html.escape(cover_image or f"{SITE_ORIGIN}/static/favicon.ico")
    product_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": ["Product", "VideoGame"],
            "name": title,
            "url": game_url,
            "image": cover_image or None,
            "description": meta_plain,
            "gamePlatform": "PC",
            "offers": {
                "@type": "AggregateOffer",
                "priceCurrency": "PLN",
                "lowPrice": f"{best_price_pln:.2f}" if best_price_pln is not None else None,
                "availability": "https://schema.org/InStock",
                "url": game_url,
            }
            if best_price_pln is not None
            else None,
        },
        ensure_ascii=False,
    )
    breadcrumb_ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "KupujPL Gry", "item": SITE_ORIGIN + "/"},
                {"@type": "ListItem", "position": 2, "name": title, "item": game_url},
                {"@type": "ListItem", "position": 3, "name": "Historia cen", "item": page_url},
            ],
        },
        ensure_ascii=False,
    )
    faqs = [
        (
            f"Jaka jest najniższa cena {title} w historii?",
            f"Według danych KupujPL rekord to {low_txt}.",
        ),
        (
            f"Ile kosztuje {title} teraz?",
            f"Aktualnie od {best_txt} — porównaj oferty na stronie gry.",
        ),
        (
            "Jak czytać wykres historii cen?",
            "Linia pokazuje najniższą dzienną cenę spośród sklepów w katalogu KupujPL.",
        ),
    ]
    faq_ld = _faq_page_schema(faqs)
    faq_html = "".join(
        f"<details><summary>{html.escape(q)}</summary><p>{html.escape(a)}</p></details>"
        for q, a in faqs
    )
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Historia cen {safe_title} — wykres cen PC | KupujPL Gry</title>
<meta name="description" content="{meta_desc}">
<meta name="robots" content="index, follow">
<link rel="canonical" href="{html.escape(page_url)}">
<meta property="og:type" content="website">
<meta property="og:title" content="Historia cen {safe_title}">
<meta property="og:description" content="{meta_desc}">
<meta property="og:image" content="{SITE_ORIGIN}/og/gra/{html.escape(slug)}.png">
<meta property="og:url" content="{html.escape(page_url)}">
<style>{_base_styles()}</style>
<script type="application/ld+json">{product_ld}</script>
<script type="application/ld+json">{breadcrumb_ld}</script>
<script type="application/ld+json">{faq_ld}</script></head>
<body>
<nav><a href="{SITE_ORIGIN}/">KupujPL Gry</a> · <a href="{html.escape(game_url)}">{safe_title}</a></nav>
<div class="seo-header">
  <img src="{img}" alt="{safe_title}" width="120" height="56">
  <div>
    <h1>Historia cen: {safe_title}</h1>
    <p class="lead">Wykres i tabela najniższych cen PC. Teraz od <strong>{best_txt}</strong>
    · rekord {low_txt} · średnia 30 dni {avg_txt}.</p>
  </div>
</div>
{chart}
<table class="history-table"><thead><tr><th>Dzień</th><th>Najniższa cena</th></tr></thead>
<tbody>{rows}</tbody></table>
<section class="faq"><h2>Pytania</h2>{faq_html}</section>
<a class="cta" href="{html.escape(game_url)}">Porównaj oferty {safe_title}</a>
</body></html>"""



def intent_guide_landing_html(*, indexable: bool = True, hub_html: str | None = None) -> str:
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
