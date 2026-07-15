"""Polish-friendly game search — title/slug only, no description noise."""
from __future__ import annotations

import os
import unicodedata

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Query

from app.models.models import Game

_PL_CHARS = str.maketrans(
    "ąćęłńóśżźĄĆĘŁŃÓŚŻŹ",
    "acelnoszzACELNOSZZ",
)

_MIN_SEARCH_QUERY_LEN = int(os.environ.get("MIN_SEARCH_QUERY_LEN", "2"))

_APOSTROPHES = ("'", "'", "`", "´", "ʼ", "′")

# Whole-query aliases (folded lowercase key) → expanded search phrase(s)
_SEARCH_ALIASES: dict[str, str | list[str]] = {
    "wiedzmin": ["witcher", "wiedzmin"],
    "wiedzma": ["witcher", "wiedzmin"],
    "wiedzmin3": "witcher 3",
    "wiedzmin 3": "witcher 3",
    "witcher": ["witcher", "wiedzmin"],
    "dziki gon": "wild hunt",
    "gta": "grand theft auto",
    "gtav": "grand theft auto",
    "gta5": "grand theft auto",
    "gta 5": "grand theft auto",
    "gta v": "grand theft auto",
    "cs2": "counter strike 2",
    "csgo": "counter strike",
    "cod": "call of duty",
    "rdr2": "red dead redemption",
    "rdr": "red dead redemption",
    "fifa": "ea sports fc",
    "fc25": "ea sports fc",
    "fc 25": "ea sports fc",
    "fc26": "ea sports fc",
    "fc 26": "ea sports fc",
    "elden": "elden ring",
    "cyberpunk": "cyberpunk 2077",
    # Assassin's Creed — PL/UA typos, apostrophe variants, Cyrillic
    "assasin": "assassin",
    "assasins": "assassin",
    "asassins": "assassin",
    "asasyn": "assassin",
    "asasyni": "assassin",
    "asasynow": "assassin",
    "asasynów": "assassin",
    "asasini": "assassin",
    "асасин": "assassin",
    "асасини": "assassin",
    "асасін": "assassin",
    "асасіни": "assassin",
    "асасінів": "assassin",
    "асасины": "assassin",
    "ac": "assassin's creed",
    "ac odyssey": "assassin's creed odyssey",
    "ac unity": "assassin's creed unity",
    "ac valhalla": "assassin's creed valhalla",
}

_FOLD_PAIRS = tuple(zip("ąćęłńóśżź", "acelnoszz"))


def _fold_title_column():
    col = func.lower(Game.title)
    for pl, en in _FOLD_PAIRS:
        col = func.replace(col, pl, en)
    return col


def fold_pl(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.translate(_PL_CHARS)


def strip_apostrophes(text: str) -> str:
    out = fold_pl(text).lower()
    for ch in _APOSTROPHES:
        out = out.replace(ch, "")
    return out


def _fold_title_plain():
    col = _fold_title_column()
    for ch in _APOSTROPHES:
        col = func.replace(col, ch, "")
    return col


def search_phrases(raw: str) -> list[str]:
    q = (raw or "").strip()
    if not q:
        return []
    phrases: list[str] = []
    candidates = [q, fold_pl(q), strip_apostrophes(q)]
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate and candidate not in phrases:
            phrases.append(candidate)
    for key in (fold_pl(q).lower(), strip_apostrophes(q)):
        alias = _SEARCH_ALIASES.get(key)
        if alias:
            for item in alias if isinstance(alias, list) else [alias]:
                if item not in phrases:
                    phrases.append(item)
    return phrases


def _title_word_clause(word: str):
    w = word.strip()
    if len(w) < 2:
        return None
    wl = strip_apostrophes(w)
    if len(wl) < 2:
        return None
    title = _fold_title_plain()
    slug = Game.slug
    if len(wl) <= 3:
        return or_(
            title == wl,
            title.like(f"{wl} %"),
            title.like(f"% {wl} %"),
            title.like(f"% {wl}"),
            slug.ilike(f"{wl}%"),
        )
    pattern = f"%{wl}%"
    return or_(title.like(pattern), slug.ilike(pattern))


def _phrase_clause(phrase: str):
    words = [w for w in phrase.split() if len(w.strip()) >= 2]
    if not words:
        return None
    parts = [_title_word_clause(word) for word in words]
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return and_(*parts)


def apply_game_search(query: Query, raw: str) -> Query:
    q = (raw or "").strip()
    if len(q) < _MIN_SEARCH_QUERY_LEN:
        return query.filter(Game.id < 0)

    phrase_clauses = []
    for phrase in search_phrases(q):
        clause = _phrase_clause(phrase)
        if clause is not None:
            phrase_clauses.append(clause)

    if not phrase_clauses:
        return query.filter(Game.id < 0)
    return query.filter(or_(*phrase_clauses))


def apply_search_quality_filter(query: Query) -> Query:
    """Drop obvious non-game rows from search results (catalog is already popularity-filtered)."""
    junk = or_(
        Game.title.ilike("%soundtrack%"),
        Game.title.ilike("%playtest%"),
        Game.title.ilike("%beta test%"),
        Game.title.ilike("% - demo"),
        Game.title.ilike("% demo"),
        Game.title.like("Gra %"),
    )
    return query.filter(~junk)


def search_order(query: Query) -> Query:
    return query.order_by(
        Game.steam_review_count.desc().nullslast(),
        Game.steam_recommendations.desc().nullslast(),
        Game.title.asc(),
    )
