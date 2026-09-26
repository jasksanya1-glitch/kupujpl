"""SEO landing registry with quality threshold (min games before index/sitemap)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.game_catalog_filter import exclude_hidden_games_query
from app.core.site_config import SITE_ORIGIN
from app.models.models import Category, Game, Offer, game_categories
from app.schemas.schemas import GameListResponse

MIN_SEO_GAMES = 8


@dataclass(frozen=True)
class SeoLanding:
    slug: str
    kind: str
    title: str
    group: str  # cena | znizka | gatunek | zamiar | inne
    max_price: int | None = None
    min_savings_pct: int | None = None
    category_slug: str | None = None
    hub_label: str | None = None

    @property
    def label(self) -> str:
        return self.hub_label or self.title


# Canonical SEO landings (genres without DB data intentionally omitted).
SEO_LANDINGS: list[SeoLanding] = [
    # Price
    SeoLanding("gry-pc-do-10-zl", "budget", "Gry PC do 10 zł", "cena", max_price=10),
    SeoLanding("gry-pc-do-20-zl", "budget", "Gry PC do 20 zł", "cena", max_price=20),
    SeoLanding("gry-pc-do-30-zl", "budget", "Gry PC do 30 zł", "cena", max_price=30),
    SeoLanding("gry-pc-do-50-zl", "budget", "Gry PC do 50 zł", "cena", max_price=50),
    SeoLanding("gry-pc-do-100-zl", "budget", "Gry PC do 100 zł", "cena", max_price=100),
    # Discount vs Steam
    SeoLanding(
        "gry-pc-znizka-50",
        "discount",
        "Gry PC −50% vs Steam",
        "znizka",
        min_savings_pct=50,
        hub_label="Gry −50%",
    ),
    SeoLanding(
        "gry-pc-znizka-70",
        "discount",
        "Gry PC −70% vs Steam",
        "znizka",
        min_savings_pct=70,
        hub_label="Gry −70%",
    ),
    SeoLanding(
        "gry-pc-znizka-80",
        "discount",
        "Gry PC −80% vs Steam",
        "znizka",
        min_savings_pct=80,
        hub_label="Gry −80%",
    ),
    SeoLanding(
        "gry-pc-znizka-90",
        "discount",
        "Gry PC −90% vs Steam",
        "znizka",
        min_savings_pct=90,
        hub_label="Gry −90%",
    ),
    # Genre (only categories that exist in DB)
    SeoLanding(
        "gry-rpg",
        "genre",
        "Gry RPG PC — porównanie cen",
        "gatunek",
        category_slug="rpg",
        hub_label="RPG",
    ),
    SeoLanding(
        "gry-strategie",
        "genre",
        "Gry strategiczne PC — porównanie cen",
        "gatunek",
        category_slug="strategie",
        hub_label="Strategie",
    ),
    SeoLanding(
        "gry-co-op",
        "genre",
        "Gry co-op PC — porównanie cen",
        "gatunek",
        category_slug="feat-kooperacja",
        hub_label="Co-op",
    ),
    # Intent
    SeoLanding(
        "najtansze-gry-steam",
        "intent_steam_cheap",
        "Najtańsze gry Steam",
        "zamiar",
        hub_label="Najtańsze gry Steam",
    ),
    SeoLanding(
        "gry-steam-tanio",
        "intent_steam_sale",
        "Gry Steam tanio",
        "zamiar",
        min_savings_pct=15,
        hub_label="Gry Steam tanio",
    ),
    SeoLanding(
        "gdzie-kupic-gry-pc-najtaniej",
        "intent_hub",
        "Gdzie kupić gry PC najtaniej",
        "zamiar",
        hub_label="Gdzie kupić najtaniej",
    ),
    # Existing evergreen deals
    SeoLanding("promocje", "promocje", "Promocje na gry PC", "inne", min_savings_pct=5),
    SeoLanding(
        "najwieksze-okazje",
        "okazje",
        "Największe okazje vs Steam",
        "inne",
        min_savings_pct=10,
        hub_label="Największe okazje",
    ),
    SeoLanding(
        "gry-z-polskim-dubbingiem",
        "dubbing",
        "Gry z polskim dubbingiem",
        "inne",
    ),
    SeoLanding(
        "igry-z-polskim-dublyazhem",
        "dubbing_uk",
        "Ігри з польським дубляжем",
        "inne",
    ),
    SeoLanding("darmowe-gry", "freebies", "Darmowe gry PC — Steam i Epic", "inne"),
]

_BY_SLUG = {x.slug: x for x in SEO_LANDINGS}

BUDGET_PRICES = (10, 20, 30, 50, 100)


def get_landing(slug: str) -> SeoLanding | None:
    return _BY_SLUG.get(slug)


def budget_canonical_slug(price: int) -> str:
    return f"gry-pc-do-{price}-zl"


def is_indexable_count(n: int) -> bool:
    return n >= MIN_SEO_GAMES


def _best_offers_map(db: Session, game_ids: list[int]) -> dict[int, Offer]:
    if not game_ids:
        return {}
    offers = (
        db.query(Offer)
        .filter(
            Offer.game_id.in_(game_ids),
            Offer.in_stock.is_(True),
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
        )
        .all()
    )
    best: dict[int, Offer] = {}
    for offer in offers:
        prev = best.get(offer.game_id)
        if prev is None or offer.price_pln < prev.price_pln:
            best[offer.game_id] = offer
    return best


def _steam_offers_map(db: Session, game_ids: list[int]) -> dict[int, Offer]:
    if not game_ids:
        return {}
    offers = (
        db.query(Offer)
        .filter(
            Offer.game_id.in_(game_ids),
            Offer.shop_name == "Steam",
            Offer.in_stock.is_(True),
            Offer.price_pln.isnot(None),
            Offer.price_pln > 0,
        )
        .all()
    )
    out: dict[int, Offer] = {}
    for offer in offers:
        prev = out.get(offer.game_id)
        if prev is None or offer.price_pln < prev.price_pln:
            out[offer.game_id] = offer
    return out


def _savings_pct(best: Offer | None, steam: Offer | None) -> int | None:
    if not best or not steam or not best.price_pln or not steam.price_pln:
        return None
    if best.price_pln >= steam.price_pln:
        return None
    savings = float(steam.price_pln) - float(best.price_pln)
    if savings < 0.01:
        return None
    return int(round((savings / float(steam.price_pln)) * 100))


GameItemBuilder = Callable[[Game, Offer | None, Offer | None], GameListResponse]


def collect_landing_items(
    db: Session,
    landing: SeoLanding,
    *,
    build_item: GameItemBuilder,
    limit: int = 60,
) -> list[GameListResponse]:
    """Build game cards for a landing; caller supplies GameListResponse builder from main."""
    kind = landing.kind

    if kind == "intent_hub":
        return []

    if kind == "budget" and landing.max_price:
        min_price = (
            db.query(Offer.game_id, func.min(Offer.price_pln).label("min_p"))
            .filter(
                Offer.in_stock.is_(True),
                Offer.price_pln > 0,
                Offer.price_pln <= landing.max_price,
            )
            .group_by(Offer.game_id)
            .subquery()
        )
        games = (
            exclude_hidden_games_query(db.query(Game))
            .join(min_price, Game.id == min_price.c.game_id)
            .order_by(min_price.c.min_p.asc())
            .limit(220)
            .all()
        )
    elif kind == "genre" and landing.category_slug:
        cat = db.query(Category).filter(Category.slug == landing.category_slug).first()
        if not cat:
            return []
        gids_q = db.query(game_categories.c.game_id).filter(
            game_categories.c.category_id == cat.id
        )
        games = (
            exclude_hidden_games_query(db.query(Game))
            .filter(Game.id.in_(gids_q))
            .limit(220)
            .all()
        )
    elif kind == "intent_steam_cheap":
        steam_min = (
            db.query(Offer.game_id, func.min(Offer.price_pln).label("min_p"))
            .filter(
                Offer.shop_name == "Steam",
                Offer.in_stock.is_(True),
                Offer.price_pln > 0,
            )
            .group_by(Offer.game_id)
            .subquery()
        )
        games = (
            exclude_hidden_games_query(db.query(Game))
            .join(steam_min, Game.id == steam_min.c.game_id)
            .order_by(steam_min.c.min_p.asc())
            .limit(220)
            .all()
        )
    elif kind in {
        "discount",
        "promocje",
        "okazje",
        "intent_steam_sale",
        "dubbing",
        "dubbing_uk",
    }:
        candidate_ids = [
            row[0]
            for row in db.query(Offer.game_id)
            .filter(Offer.in_stock.is_(True), Offer.price_pln > 0)
            .distinct()
            .limit(500)
            .all()
        ]
        q = exclude_hidden_games_query(db.query(Game)).filter(Game.id.in_(candidate_ids))
        if kind in ("dubbing", "dubbing_uk"):
            q = q.filter(Game.has_polish_audio.is_(True))
        games = q.limit(300).all()
    elif kind == "freebies":
        return []  # handled by existing freebies renderer
    else:
        return []

    gids = [g.id for g in games]
    best_map = _best_offers_map(db, gids)
    steam_map = _steam_offers_map(db, gids)
    items: list[GameListResponse] = []

    for game in games:
        best = best_map.get(game.id)
        steam = steam_map.get(game.id)
        if kind == "intent_steam_cheap":
            if not steam:
                continue
            item = build_item(game, steam, steam)
        else:
            if not best:
                continue
            item = build_item(game, best, steam)

        pct = item.savings_pct if item.savings_pct is not None else _savings_pct(best, steam)

        if kind == "budget" and landing.max_price:
            if (item.best_price_pln or 9999) > landing.max_price:
                continue
        if kind == "discount" and landing.min_savings_pct:
            if (pct or 0) < landing.min_savings_pct:
                continue
        if kind == "promocje" and (pct or 0) < 5:
            continue
        if kind == "okazje" and (pct or 0) < 10:
            continue
        if kind == "intent_steam_sale":
            if not steam or not best:
                continue
            # Sale angle: market best meaningfully below Steam
            if (pct or 0) < (landing.min_savings_pct or 15):
                continue
        if kind in ("dubbing", "dubbing_uk") and not best:
            continue

        items.append(item)

    if kind in ("budget", "intent_steam_cheap", "genre"):
        items.sort(key=lambda x: (x.best_price_pln is None, x.best_price_pln or 9999))
    else:
        items.sort(
            key=lambda x: (x.savings_pct or 0, -(x.best_price_pln or 9999)),
            reverse=True,
        )
    return items[:limit]


def estimate_landing_count(db: Session, landing: SeoLanding, *, build_item: GameItemBuilder) -> int:
    if landing.kind == "intent_hub":
        return MIN_SEO_GAMES  # always indexable hub
    if landing.kind == "freebies":
        # Evergreen page — keep in sitemap when any freebies exist
        n = db.query(Game).filter(Game.is_free.is_(True)).limit(20).count()
        return n if n else MIN_SEO_GAMES
    if landing.kind in ("dubbing", "dubbing_uk"):
        n = (
            exclude_hidden_games_query(db.query(Game))
            .filter(Game.has_polish_audio.is_(True))
            .limit(20)
            .count()
        )
        return n
    if landing.kind == "budget" and landing.max_price:
        min_price = (
            db.query(Offer.game_id, func.min(Offer.price_pln).label("min_p"))
            .filter(
                Offer.in_stock.is_(True),
                Offer.price_pln > 0,
                Offer.price_pln <= landing.max_price,
            )
            .group_by(Offer.game_id)
            .subquery()
        )
        return (
            exclude_hidden_games_query(db.query(Game))
            .join(min_price, Game.id == min_price.c.game_id)
            .count()
        )
    if landing.kind == "genre" and landing.category_slug:
        cat = db.query(Category).filter(Category.slug == landing.category_slug).first()
        if not cat:
            return 0
        return int(cat.game_count or 0)
    # Discount / promo / steam sale / dubbing: sample collect
    items = collect_landing_items(db, landing, build_item=build_item, limit=MIN_SEO_GAMES)
    if len(items) >= MIN_SEO_GAMES:
        return len(items)
    # try larger limit once
    return len(collect_landing_items(db, landing, build_item=build_item, limit=120))


def indexable_landings(
    db: Session,
    *,
    build_item: GameItemBuilder,
) -> list[SeoLanding]:
    out: list[SeoLanding] = []
    for landing in SEO_LANDINGS:
        n = estimate_landing_count(db, landing, build_item=build_item)
        if is_indexable_count(n):
            out.append(landing)
    return out


def hub_links_html(indexable: list[SeoLanding] | None = None) -> str:
    """Grouped hub links; if indexable is None, show safe evergreen set."""
    groups = {
        "cena": ("Cena", []),
        "znizka": ("Zniżka", []),
        "gatunek": ("Gatunek", []),
        "zamiar": ("Poradniki", []),
        "inne": ("Więcej", []),
    }
    source = indexable
    if source is None:
        # Static safe links (known-large) when DB not available at render time
        source = [
            x
            for x in SEO_LANDINGS
            if x.slug
            in {
                "gry-pc-do-10-zl",
                "gry-pc-do-20-zl",
                "gry-pc-do-30-zl",
                "gry-pc-do-50-zl",
                "gry-pc-do-100-zl",
                "gry-pc-znizka-50",
                "gry-pc-znizka-70",
                "gry-rpg",
                "gry-strategie",
                "gry-co-op",
                "najtansze-gry-steam",
                "gry-steam-tanio",
                "gdzie-kupic-gry-pc-najtaniej",
                "promocje",
                "najwieksze-okazje",
                "gry-z-polskim-dubbingiem",
                "darmowe-gry",
            }
        ]
    for landing in source:
        if landing.group in groups:
            groups[landing.group][1].append(landing)

    parts: list[str] = ['<div class="seo-hub">']
    for key, (label, items) in groups.items():
        if not items:
            continue
        parts.append(f'<p class="hub-group"><span class="hub-label">{label}:</span> ')
        links = [
            f'<a href="{SITE_ORIGIN}/{x.slug}">{x.label}</a>' for x in items
        ]
        parts.append(" · ".join(links))
        parts.append("</p>")
    parts.append("</div>")
    return "".join(parts)


def intent_hub_html(*, indexable: list[SeoLanding] | None = None) -> dict[str, Any]:
    """Content blocks for gdzie-kupic-gry-pc-najtaniej."""
    return {
        "title": "Gdzie kupić gry PC najtaniej",
        "lead": (
            "KupujPL porównuje ceny gier PC w Steam, GOG, Epic i sklepach z kluczami. "
            "Zamiast kupować od razu na Steam — sprawdź budżetowe listy, przeceny vs Steam "
            "i alert cenowy."
        ),
        "sections": [
            (
                "Ustal budżet",
                "Zacznij od list cenowych: gry do 10, 20, 30, 50 lub 100 zł.",
            ),
            (
                "Szukaj dużej różnicy vs Steam",
                "Filtry −50% / −70% / −80% / −90% pokazują, gdzie marketplace jest wyraźnie tańszy.",
            ),
            (
                "Włącz alert",
                "Śledź grę i ustaw powiadomienie — dostaniesz sygnał, gdy cena spadnie.",
            ),
        ],
        "hub": hub_links_html(indexable),
    }
