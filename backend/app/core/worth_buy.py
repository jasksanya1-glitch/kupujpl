"""Czy warto kupić? — signature KupujPL buy-worthiness score (0–100)."""
from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Literal

Tier = Literal["buy", "maybe", "wait"]


@dataclass(frozen=True)
class WorthBuyResult:
    score: int
    tier: Tier
    label: str
    reason: str
    emoji: str


def _clamp(n: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, n))


def _hist_component(price: float, hist_low: float | None) -> float | None:
    if hist_low is None or hist_low <= 0:
        return None
    ratio = price / hist_low
    if ratio <= 1.01:
        return 100.0
    if ratio <= 1.05:
        return 88.0
    if ratio <= 1.12:
        return 72.0
    if ratio <= 1.25:
        return 48.0
    if ratio <= 1.45:
        return 22.0
    return 5.0


def _avg_component(price: float, avg_30d: float | None) -> float | None:
    if avg_30d is None or avg_30d <= 0:
        return None
    ratio = price / avg_30d
    if ratio <= 0.88:
        return 100.0
    if ratio <= 0.95:
        return 86.0
    if ratio <= 1.00:
        return 72.0
    if ratio <= 1.05:
        return 48.0
    if ratio <= 1.12:
        return 28.0
    if ratio <= 1.25:
        return 12.0
    return 4.0


def _steam_component(
    price: float,
    steam_price: float | None,
    savings_pct: int | None,
) -> float | None:
    pct = savings_pct
    if pct is None and steam_price and steam_price > 0:
        if price < steam_price:
            pct = int(round((1.0 - price / steam_price) * 100))
        else:
            pct = 0
    if pct is None:
        return None
    if pct >= 55:
        return 100.0
    if pct >= 40:
        return 88.0
    if pct >= 25:
        return 74.0
    if pct >= 15:
        return 58.0
    if pct >= 8:
        return 40.0
    if pct >= 1:
        return 24.0
    return 8.0


def _discount_component(savings_pct: int | None) -> float | None:
    """Extra signal for deep discount magnitude (same axis as Steam, lighter weight)."""
    if savings_pct is None:
        return None
    return _clamp(savings_pct * 1.35)


def compute_worth_buy(
    *,
    current_price: float | None,
    avg_best_price_30d: float | None = None,
    lowest_ever_pln: float | None = None,
    steam_price_pln: float | None = None,
    savings_pct: int | None = None,
    at_historical_low: bool = False,
) -> WorthBuyResult | None:
    if current_price is None or current_price <= 0:
        return None

    parts: list[tuple[float, float]] = []  # (score, weight)

    hist = _hist_component(current_price, lowest_ever_pln)
    if at_historical_low and hist is not None:
        hist = max(hist, 96.0)
    if hist is not None:
        parts.append((hist, 0.32))

    avg = _avg_component(current_price, avg_best_price_30d)
    if avg is not None:
        parts.append((avg, 0.28))

    steam = _steam_component(current_price, steam_price_pln, savings_pct)
    if steam is not None:
        parts.append((steam, 0.25))

    disc = _discount_component(savings_pct)
    if disc is not None:
        parts.append((disc, 0.15))

    if not parts:
        return None

    total_w = sum(w for _, w in parts)
    score = int(round(sum(s * w for s, w in parts) / total_w))
    score = int(_clamp(score))

    if score >= 75:
        tier: Tier = "buy"
        emoji = "🟢"
        label = "KUP TERAZ"
        if at_historical_low or (lowest_ever_pln and current_price <= lowest_ever_pln * 1.02):
            reason = "Cena jest bardzo dobra — blisko historycznego minimum."
        elif savings_pct and savings_pct >= 25:
            reason = f"Cena jest bardzo dobra — ok. {savings_pct}% taniej niż na Steam."
        elif avg_best_price_30d and current_price < avg_best_price_30d:
            reason = "Cena jest bardzo dobra — poniżej średniej z 30 dni."
        else:
            reason = "Cena jest bardzo dobra względem dostępnych sygnałów."
    elif score >= 45:
        tier = "maybe"
        emoji = "🟡"
        label = "MOŻESZ POCZEKAĆ"
        if avg_best_price_30d and current_price > avg_best_price_30d * 1.03:
            reason = "Cena jest przeciętna — drożej niż średnia z 30 dni."
        elif savings_pct is not None and savings_pct < 15:
            reason = "Różnica vs Steam jest umiarkowana — warto obserwować."
        else:
            reason = "Cena jest OK, ale nie rewelacyjna — możesz poczekać na lepszy moment."
    else:
        tier = "wait"
        emoji = "🔴"
        label = "POCZEKAJ"
        if lowest_ever_pln and current_price > lowest_ever_pln * 1.35:
            reason = "Cena jest wysoka względem historycznego minimum."
        elif avg_best_price_30d and current_price > avg_best_price_30d * 1.1:
            reason = "Cena jest wyraźnie powyżej średniej z 30 dni."
        else:
            reason = "Na razie lepiej poczekać — sygnały cenowe są słabe."

    return WorthBuyResult(score=score, tier=tier, label=label, reason=reason, emoji=emoji)


def worth_buy_html(result: WorthBuyResult | None) -> str:
    if not result:
        return ""
    tier_class = {
        "buy": "is-buy",
        "maybe": "is-maybe",
        "wait": "is-wait",
    }[result.tier]
    return (
        f'<div class="worth-buy {tier_class}" id="gp-worth-buy" '
        f'data-score="{result.score}" data-tier="{result.tier}">'
        f'<p class="worth-buy-kicker" data-i18n="game.worth_title">Czy warto kupić?</p>'
        f'<p class="worth-buy-score">'
        f'<span class="worth-buy-emoji" aria-hidden="true">{result.emoji}</span> '
        f'<strong class="worth-buy-points">{result.score}/100</strong>'
        f'<span class="worth-buy-label"> — {html.escape(result.label)}</span>'
        f"</p>"
        f'<p class="worth-buy-reason">{html.escape(result.reason)}</p>'
        f"</div>"
    )
