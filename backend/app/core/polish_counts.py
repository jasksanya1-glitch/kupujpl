"""Polish (and simple EN/UK) catalogue count formatters.

Use these instead of hardcoded store-count marketing strings.

Source counts (single definitions — do not invent parallel meanings):
- store_count: len(display_shops_for_region("pl")) — public PL storefronts
  shown in marketing copy (Steam US excluded). Same as API stores_total.
- game_count: get_visible_games_count(db) — public catalogue games available
  to users (indexable / listable). Same as API games_total.
"""
from __future__ import annotations


def _pl_plural_form(n: int) -> str:
    """Return Polish plural category: one | few | many."""
    n = abs(int(n))
    if n == 1:
        return "one"
    mod10 = n % 10
    mod100 = n % 100
    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return "few"
    return "many"


def format_store_count(store_count: int) -> str:
    """Nominative/genitive-style count label: 1 sklep / 3 sklepy / N sklepów."""
    n = max(0, int(store_count))
    form = _pl_plural_form(n)
    if form == "one":
        return f"{n} sklep"
    if form == "few":
        return f"{n} sklepy"
    return f"{n} sklepów"


def format_store_count_locative(store_count: int) -> str:
    """Locative phrase without leading „w”: 1 sklepie / N sklepach."""
    n = max(0, int(store_count))
    if n == 1:
        return f"{n} sklepie"
    return f"{n} sklepach"


def format_in_stores(store_count: int) -> str:
    """Full locative phrase, e.g. w N sklepach."""
    return f"w {format_store_count_locative(store_count)}"


def format_game_count(game_count: int) -> str:
    """„1 gra”, „3 gry”, „10 gier”."""
    n = max(0, int(game_count))
    form = _pl_plural_form(n)
    if form == "one":
        return f"{n} gra"
    if form == "few":
        return f"{n} gry"
    return f"{n} gier"


def format_store_count_en(store_count: int) -> str:
    n = max(0, int(store_count))
    return f"{n} store" if n == 1 else f"{n} stores"


def format_store_count_uk(store_count: int) -> str:
    n = max(0, int(store_count))
    # Simplified Ukrainian genitive plural for marketing counts.
    if n == 1:
        return f"{n} магазин"
    mod10 = n % 10
    mod100 = n % 100
    if mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        return f"{n} магазини"
    return f"{n} магазинів"
