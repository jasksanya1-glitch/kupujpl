"""Manual homepage spotlight curation (owner panel)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.slug_lookup import resolve_game_slug
from app.models.models import Game
from app.parsers.steam_catalog import fetch_appdetails, slugify, upsert_game_stub
from app.core.steam_media import is_low_res_steam_cover, normalize_cover_url, steam_cover_url

CURATION_FILE = Path(__file__).resolve().parent.parent / "data" / "home_curation.json"
MAX_SPOTLIGHT = 8

_STEAM_APP_RE = re.compile(
    r"(?:store\.steampowered\.com/app/(\d+)|(?:^|\s)(\d{4,8})(?:\s|$))",
    re.I,
)


def _default_payload() -> dict[str, Any]:
    return {"spotlight_slugs": [], "updated_at": None}


def load_curation() -> dict[str, Any]:
    if not CURATION_FILE.is_file():
        return _default_payload()
    try:
        data = json.loads(CURATION_FILE.read_text(encoding="utf-8"))
        slugs = data.get("spotlight_slugs") or []
        if not isinstance(slugs, list):
            slugs = []
        clean = []
        seen: set[str] = set()
        for raw in slugs:
            slug = str(raw or "").strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            clean.append(slug)
            if len(clean) >= MAX_SPOTLIGHT:
                break
        return {
            "spotlight_slugs": clean,
            "updated_at": data.get("updated_at"),
        }
    except Exception:
        return _default_payload()


def save_curation(slugs: list[str]) -> dict[str, Any]:
    clean: list[str] = []
    seen: set[str] = set()
    for raw in slugs:
        slug = str(raw or "").strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        clean.append(slug)
        if len(clean) >= MAX_SPOTLIGHT:
            break
    payload = {
        "spotlight_slugs": clean,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    CURATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    CURATION_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def parse_steam_appid(text: str) -> int | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)
    m = _STEAM_APP_RE.search(raw)
    if not m:
        return None
    appid = m.group(1) or m.group(2)
    return int(appid) if appid else None


def resolve_games_by_slugs(db: Session, slugs: list[str]) -> list[Game]:
    out: list[Game] = []
    for slug in slugs:
        game = resolve_game_slug(db, slug.strip())
        if game:
            out.append(game)
    return out


def _steam_header_cover(appid: int) -> str | None:
    data = fetch_appdetails(appid)
    if not data:
        return None
    return normalize_cover_url(data.get("header_image"))


def _apply_steam_import_metadata(db: Session, game: Game, appid: int) -> Game:
    data = fetch_appdetails(appid)
    title = (data or {}).get("name") or game.title
    header = normalize_cover_url((data or {}).get("header_image"))
    game.title = title or game.title
    if header and not is_low_res_steam_cover(header):
        game.cover_image = header
    elif not game.cover_image:
        game.cover_image = header or steam_cover_url(appid)
    db.commit()
    db.refresh(game)
    return game


def ensure_game_cover(db: Session, game: Game) -> None:
    """Upgrade low-res Steam thumb to header_image from appdetails."""
    if not game.steam_appid:
        return
    if game.cover_image and not is_low_res_steam_cover(game.cover_image):
        return
    header = _steam_header_cover(game.steam_appid)
    if header and not is_low_res_steam_cover(header):
        game.cover_image = header
        db.commit()


def import_game_from_steam(db: Session, url_or_appid: str) -> Game:
    appid = parse_steam_appid(url_or_appid)
    if not appid:
        raise ValueError("Nie rozpoznano linku Steam ani appid")
    existing = db.query(Game).filter(Game.steam_appid == appid).first()
    if existing:
        if is_low_res_steam_cover(existing.cover_image):
            return _apply_steam_import_metadata(db, existing, appid)
        return existing
    data = fetch_appdetails(appid)
    title = (data or {}).get("name") or f"Gra {appid}"
    cover = normalize_cover_url((data or {}).get("header_image")) or steam_cover_url(appid)
    game = upsert_game_stub(db, appid, title, cover)
    db.commit()
    db.refresh(game)
    return game
