"""Server-render first homepage cards for crawlers / no-JS (Design Concept #3 intact)."""
from __future__ import annotations

import html
import re
from typing import Any

from sqlalchemy.orm import Session

from app.core.articles import list_published_articles
from app.core.game_catalog_filter import get_visible_games_count
from app.core.game_offer_selection import best_offers_map, display_shops_for_region, steam_offers_map
from app.core.home_curation import load_curation
from app.core.polish_counts import (
    format_game_count,
    format_in_stores,
    format_store_count,
    format_store_count_locative,
)
from app.models.models import Game, Offer
from app.schemas.schemas import GameListResponse

_HOME_SSR_GAME_LIMIT = 18
_HOME_SSR_NEWS_LIMIT = 4


def catalog_store_count(*, region: str = "pl") -> int:
    """Public storefront count for marketing copy (PL excludes Steam US)."""
    return len(display_shops_for_region(region))


def _price_txt(price: float | None) -> str:
    if price is None:
        return "—"
    return f"{float(price):.2f} zł"


def _game_ssr_card(game: GameListResponse, *, eager: bool = False) -> str:
    href = f"gra/{html.escape(game.slug)}"
    title = html.escape(game.title or "")
    price = html.escape(_price_txt(game.best_price_pln))
    shop = html.escape(game.best_shop_name or "")
    img = ""
    if game.cover_image:
        loading = "eager" if eager else "lazy"
        prio = ' fetchpriority="high"' if eager else ""
        img = (
            f'<img src="{html.escape(game.cover_image)}" alt="{title}" '
            f'width="460" height="215" loading="{loading}" decoding="async"{prio}>'
        )
    shop_bit = f'<span class="ssr-card-shop">{shop}</span>' if shop else ""
    return (
        f'<a class="ssr-game-card game-card" href="{href}">'
        f'<span class="ssr-card-cover card-cover">{img}</span>'
        f'<span class="ssr-card-body card-body">'
        f'<strong class="card-title">{title}</strong>'
        f'<span class="card-price">{price}</span>{shop_bit}'
        f"</span></a>"
    )


def _build_list_item(game: Game, best: Offer | None, steam: Offer | None) -> GameListResponse:
    steam_price = float(steam.price_pln) if steam and steam.price_pln else None
    best_price = float(best.price_pln) if best and best.price_pln else None
    savings_pct = None
    if steam_price and best_price and best_price < steam_price:
        savings_pct = int(round(((steam_price - best_price) / steam_price) * 100))
    return GameListResponse(
        id=game.id,
        title=game.title or "",
        slug=game.slug or "",
        cover_image=game.cover_image,
        steam_appid=game.steam_appid,
        platform=getattr(game, "platform", None) or "pc",
        best_price_pln=best_price,
        best_shop_name=best.shop_name if best else None,
        best_price_is_official=bool(best.is_official) if best else None,
        steam_price_pln=steam_price,
        savings_pct=savings_pct,
        lowest_ever_pln=getattr(game, "lowest_ever_pln", None),
        is_free=bool(getattr(game, "is_free", False)),
    )


def _spotlight_items(db: Session) -> list[GameListResponse]:
    curation = load_curation()
    slugs = [s for s in (curation.get("spotlight_slugs") or []) if s]
    if not slugs:
        return []
    rows = db.query(Game).filter(Game.slug.in_(slugs)).all()
    by_slug = {g.slug: g for g in rows}
    ids = [by_slug[s].id for s in slugs if s in by_slug]
    if not ids:
        return []
    games_by_id = {g.id: g for g in rows}
    best_map = best_offers_map(db, ids, region="pl", games=games_by_id)
    steam_map = steam_offers_map(db, ids, shop_name="Steam")
    out: list[GameListResponse] = []
    for slug in slugs:
        game = by_slug.get(slug)
        if not game:
            continue
        best = best_map.get(game.id)
        if not best:
            continue
        out.append(_build_list_item(game, best, steam_map.get(game.id)))
    return out


def _first_catalog_items(db: Session, limit: int = _HOME_SSR_GAME_LIMIT) -> list[GameListResponse]:
    rows = (
        db.query(Game)
        .filter(Game.slug.isnot(None), Game.slug != "")
        .order_by(Game.steam_review_count.desc().nulls_last(), Game.id.asc())
        .limit(limit * 3)
        .all()
    )
    if not rows:
        return []
    ids = [g.id for g in rows]
    games_by_id = {g.id: g for g in rows}
    best_map = best_offers_map(db, ids, region="pl", games=games_by_id)
    steam_map = steam_offers_map(db, ids, shop_name="Steam")
    out: list[GameListResponse] = []
    for g in rows:
        best = best_map.get(g.id)
        if not best:
            continue
        out.append(_build_list_item(g, best, steam_map.get(g.id)))
        if len(out) >= limit:
            break
    return out


def build_homepage_ssr_fragments(db: Session) -> dict[str, str]:
    """Return HTML fragments keyed by injection target id/marker."""
    stores = catalog_store_count()
    games_total = get_visible_games_count(db)
    spotlight = _spotlight_items(db)
    catalog = _first_catalog_items(db)
    arts = list_published_articles(db, limit=_HOME_SSR_NEWS_LIMIT)

    hero_html = ""
    side_html = ""
    if spotlight:
        first = spotlight[0]
        href = f"gra/{html.escape(first.slug)}"
        title = html.escape(first.title or "")
        price = html.escape(_price_txt(first.best_price_pln))
        shop = html.escape(first.best_shop_name or "")
        img_src = html.escape(first.cover_image or "")
        img_tag = (
            f'<img id="d3-hero-img" src="{img_src}" alt="{title}" width="1600" height="600" '
            f'decoding="async" fetchpriority="high">'
            if img_src
            else '<img id="d3-hero-img" src="" alt="" width="1600" height="600" decoding="async" fetchpriority="high">'
        )
        price_block = (
            f'<span class="d3-hero-now">{price}</span>'
            f'<span class="d3-hero-best">Najlepsza cena'
            f'{f" · {shop}" if shop else ""}</span>'
        )
        hero_html = (
            f'<a class="d3-hero-main" id="d3-hero-main" href="{href}">'
            f'<div class="d3-hero-media">{img_tag}</div>'
            f'<div class="d3-hero-overlay">'
            f'<p class="d3-hero-label" data-i18n="d3.featured_label">Polecana gra</p>'
            f'<h2 class="d3-hero-title" id="d3-hero-title">{title}</h2>'
            f'<p class="d3-hero-sub" id="d3-hero-sub" hidden></p>'
            f'<div class="d3-hero-tags" id="d3-hero-tags"></div>'
            f'<div class="d3-hero-price" id="d3-hero-price">{price_block}</div>'
            f'<span class="d3-hero-cta" data-i18n="d3.compare">Porównaj ceny →</span>'
            f"</div></a>"
        )
        for game in spotlight[1:5]:
            ghref = f"gra/{html.escape(game.slug)}"
            gtitle = html.escape(game.title or "")
            gprice = html.escape(_price_txt(game.best_price_pln))
            cover = html.escape(game.cover_image or "")
            side_html += (
                f'<a class="d3-side-row" href="{ghref}" data-slug="{html.escape(game.slug)}">'
                f'<span class="d3-side-cover"><img src="{cover}" alt="" width="88" height="42" '
                f'loading="eager" decoding="async"></span>'
                f'<span class="d3-side-meta">'
                f'<span class="d3-side-title">{gtitle}</span>'
                f'<span class="d3-side-price">{gprice}</span>'
                f"</span>"
                f'<span class="d3-side-chevron" aria-hidden="true">›</span>'
                f"</a>"
            )

    news_html = ""
    for art in arts:
        href = f"blog/{html.escape(art.slug)}"
        title = html.escape(art.title or "")
        dt = getattr(art, "date_published", None) or getattr(art, "date_created", None)
        date_txt = html.escape(dt.strftime("%Y-%m-%d")) if dt else ""
        date_bit = f'<time datetime="{date_txt}">{date_txt}</time>' if date_txt else ""
        img = getattr(art, "featured_image", None) or ""
        img_bit = ""
        if img:
            img_bit = (
                f'<img src="{html.escape(img)}" alt="" width="320" height="180" '
                f'loading="lazy" decoding="async">'
            )
        news_html += (
            f'<a class="home-news-item" href="{href}">'
            f"{img_bit}<strong>{title}</strong>{date_bit}</a>"
        )

    # Cards only — injected into #games-grid AFTER the "Wszystkie gry" header.
    games_html = "".join(
        _game_ssr_card(g, eager=(i == 0)) for i, g in enumerate(catalog)
    )

    return {
        "stores": str(stores),
        "stores_label": format_store_count(stores),
        "stores_locative": format_store_count_locative(stores),
        "in_stores": format_in_stores(stores),
        "games_total": f"{games_total:,}".replace(",", " "),
        "games_total_raw": str(games_total),
        "games_label": format_game_count(games_total),
        "hero_main": hero_html,
        "hero_side": side_html,
        "news": news_html,
        "games": games_html,
        "has_spotlight": "1" if spotlight else "0",
        "has_news": "1" if arts else "0",
        "has_games": "1" if games_html else "0",
    }


_HERO_MAIN_RE = re.compile(
    r'<a class="d3-hero-main" id="d3-hero-main"[\s\S]*?</a>',
    re.I,
)
_HERO_SIDE_RE = re.compile(
    r'(<div class="d3-hero-side-list" id="d3-hero-side-list">)([\s\S]*?)(</div>)',
    re.I,
)
_NEWS_LIST_RE = re.compile(
    r'(<div id="home-news-list" class="home-news-list">)([\s\S]*?)(</div>)',
    re.I,
)
_GAMES_GRID_RE = re.compile(
    r'(<div id="games-grid" class="grid">)([\s\S]*?)(</div>)',
    re.I,
)
_CATALOG_SECTION_RE = re.compile(
    r'<section id="catalog-section" class="catalog"[^>]*>',
    re.I,
)
_HOME_NEWS_SECTION_RE = re.compile(
    r'<section id="home-news" class="home-news"[^>]*>',
    re.I,
)
_D3_HERO_RE = re.compile(
    r'<section id="d3-hero" class="d3-hero"[^>]*>',
    re.I,
)


def inject_homepage_ssr(html_doc: str, fragments: dict[str, str]) -> str:
    out = html_doc
    stores_n = fragments.get("stores") or str(catalog_store_count())
    stores_label = fragments.get("stores_label") or format_store_count(int(stores_n))
    stores_loc = fragments.get("stores_locative") or format_store_count_locative(int(stores_n))
    in_stores = fragments.get("in_stores") or format_in_stores(int(stores_n))
    games_fmt = fragments.get("games_total") or fragments.get("games_total_raw") or "…"
    games_label = fragments.get("games_label") or games_fmt

    # Explicit placeholders from catalogue status (preferred).
    out = out.replace("__STORE_COUNT__", stores_n)
    out = out.replace("__STORE_COUNT_LABEL__", stores_label)
    out = out.replace("__STORE_COUNT_LOCATIVE__", stores_loc)
    out = out.replace("__IN_STORES__", in_stores)
    out = out.replace("__GAME_COUNT__", games_fmt)
    out = out.replace("__GAME_COUNT_LABEL__", games_label)

    if fragments.get("hero_main"):
        out = _HERO_MAIN_RE.sub(fragments["hero_main"], out, count=1)
        out = _D3_HERO_RE.sub(
            '<section id="d3-hero" class="d3-hero" data-i18n-aria="d3.featured_list" aria-label="Polecane gry">',
            out,
            count=1,
        )
    if fragments.get("hero_side") is not None:
        out = _HERO_SIDE_RE.sub(
            rf'\1{fragments["hero_side"]}\3',
            out,
            count=1,
        )
    if fragments.get("news"):
        out = _NEWS_LIST_RE.sub(rf'\1{fragments["news"]}\3', out, count=1)
        out = _HOME_NEWS_SECTION_RE.sub(
            '<section id="home-news" class="home-news" aria-labelledby="home-news-title">',
            out,
            count=1,
        )
    if fragments.get("games"):
        # Semantic order: catalog header (H2) already precedes #games-grid in template.
        out = _GAMES_GRID_RE.sub(
            rf'\1{fragments["games"]}\3',
            out,
            count=1,
        )
        # Expose catalogue to no-JS / crawlers (JS still toggles visibility).
        out = _CATALOG_SECTION_RE.sub(
            '<section id="catalog-section" class="catalog" data-ssr-catalog="1" aria-labelledby="games-heading">',
            out,
            count=1,
        )
        # Avoid a spinner block appearing before the real catalogue in raw HTML.
        out = re.sub(
            r'<section id="home-sections" class="sections"[^>]*>',
            '<section id="home-sections" class="sections" hidden data-ssr-skip="1">',
            out,
            count=1,
            flags=re.I,
        )
    return out


def safe_homepage_ssr(db: Session | None) -> dict[str, Any]:
    if db is None:
        return {}
    try:
        return build_homepage_ssr_fragments(db)
    except Exception:
        return {}
