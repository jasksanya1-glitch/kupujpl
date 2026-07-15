"""Full catalog enrich + offer refresh for all games and shops (run on VPS)."""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func

from app.core.database import SessionLocal, BASE_DIR
from app.models.models import Game, Offer
from app.parsers.steam_catalog import enrich_pending_batch, get_catalog_progress
from app.parsers.game_offers import refresh_offers_for_game, EXPECTED_SHOPS
from app.parsers.gog_parser import import_gog_offers
from app.parsers.epic_parser import import_epic_offers
from app.parsers.kinguin_parser import import_kinguin_offers
from app.parsers.eneba_parser import import_eneba_offers
from app.parsers.cdkeys_parser import import_cdkeys_offers
from app.parsers.g2a_parser import import_g2a_offers
from app.parsers.gamivo_parser import import_gamivo_offers
from app.parsers.instant_gaming_parser import import_instant_gaming_offers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [full_scan] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("full_scan")

STATE_PATH = BASE_DIR / "tmp" / "full_scan_state.json"
ENRICH_BATCH = int(os.environ.get("FULL_SCAN_ENRICH_BATCH", "500"))
OFFER_BATCH = int(os.environ.get("FULL_SCAN_OFFER_BATCH", "50"))
OFFER_DELAY = float(os.environ.get("FULL_SCAN_OFFER_DELAY_SEC", "1.0"))
SHOP_IMPORT_LIMIT = int(os.environ.get("FULL_SCAN_SHOP_LIMIT", "500"))


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _load_state() -> dict:
    if STATE_PATH.is_file():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"started_at": _utcnow(), "phase": "enrich"}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _utcnow()
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _counts() -> dict:
    db = SessionLocal()
    try:
        total = db.query(Game).count()
        enriched = db.query(Game).filter(Game.steam_enriched == True).count()
        pending = db.query(Game).filter(
            Game.steam_appid.isnot(None), Game.steam_enriched == False
        ).count()
        offers = {
            name: cnt
            for name, cnt in db.query(Offer.shop_name, func.count(Offer.id)).group_by(Offer.shop_name).all()
        }
        return {"total_games": total, "enriched": enriched, "pending_enrich": pending, "offers_by_shop": offers}
    finally:
        db.close()


def run_enrich_phase(state: dict) -> bool:
    """Return True when enrich phase complete."""
    db = SessionLocal()
    try:
        pending = (
            db.query(Game)
            .filter(Game.steam_appid.isnot(None), Game.steam_enriched == False)
            .count()
        )
    finally:
        db.close()

    if pending == 0:
        log.info("Enrich complete — no pending games")
        return True

    log.info("Enriching batch (pending=%s, batch=%s)", pending, ENRICH_BATCH)
    db = SessionLocal()
    try:
        result = enrich_pending_batch(db, limit=ENRICH_BATCH)
    finally:
        db.close()

    state["enrich"] = result
    state["counts"] = _counts()
    _save_state(state)
    log.info("Enrich batch: %s", result)
    return result.get("remaining", pending) == 0


def run_offers_phase(state: dict) -> bool:
    """Refresh offers for enriched games; return True when all processed."""
    offset = int(state.get("offer_offset", 0))
    db = SessionLocal()
    try:
        game_ids = [
            g.id
            for g in (
                db.query(Game.id)
                .filter(Game.steam_enriched == True)
                .order_by(Game.rating.desc().nulls_last(), Game.id)
                .offset(offset)
                .limit(OFFER_BATCH)
                .all()
            )
        ]
        total_enriched = db.query(Game).filter(Game.steam_enriched == True).count()
    finally:
        db.close()

    if not game_ids:
        log.info("Offers phase complete — processed %s games", offset)
        return True

    refreshed = errors = 0
    for gid in game_ids:
        try:
            refresh_offers_for_game(gid, force=True, fill_missing=True, fast=False)
            refreshed += 1
        except Exception as exc:
            errors += 1
            log.warning("Offer refresh failed game=%s: %s", gid, exc)
        time.sleep(OFFER_DELAY)

    offset += len(game_ids)
    state["offer_offset"] = offset
    state["offer_total"] = total_enriched
    state["last_offer_batch"] = {"refreshed": refreshed, "errors": errors, "offset": offset}
    state["counts"] = _counts()
    _save_state(state)
    log.info(
        "Offers batch: %s/%s enriched (+%s ok, %s err)",
        offset,
        total_enriched,
        refreshed,
        errors,
    )
    return offset >= total_enriched


def run_shop_imports(state: dict) -> None:
    importers = [
        ("GOG", import_gog_offers),
        ("Epic Games", import_epic_offers),
        ("Instant Gaming", import_instant_gaming_offers),
        ("Kinguin", import_kinguin_offers),
        ("Eneba", import_eneba_offers),
        ("CDKeys", import_cdkeys_offers),
        ("Gamivo", import_gamivo_offers),
        ("G2A", import_g2a_offers),
    ]
    results = {}
    db = SessionLocal()
    try:
        for name, fn in importers:
            try:
                results[name] = fn(db, limit=SHOP_IMPORT_LIMIT)
                log.info("Shop import %s: %s", name, results[name])
            except Exception as exc:
                results[name] = {"error": str(exc)}
                log.warning("Shop import %s failed: %s", name, exc)
            time.sleep(2)
    finally:
        db.close()
    state["shop_imports"] = results
    state["counts"] = _counts()
    _save_state(state)


def main() -> None:
    log.info("Full scan started (shops: %s)", ", ".join(EXPECTED_SHOPS))
    state = _load_state()
    if "started_at" not in state:
        state["started_at"] = _utcnow()
    state["counts"] = _counts()
    _save_state(state)
    log.info("Initial counts: %s", state["counts"])

    while state.get("phase") != "done":
        phase = state.get("phase", "enrich")
        try:
            if phase == "enrich":
                if run_enrich_phase(state):
                    state["phase"] = "offers"
                    state["offer_offset"] = 0
                    _save_state(state)
                    log.info("Switching to offers phase")
                else:
                    time.sleep(5)
            elif phase == "offers":
                if run_offers_phase(state):
                    state["phase"] = "shops"
                    _save_state(state)
                    log.info("Switching to shop imports phase")
                else:
                    time.sleep(3)
            elif phase == "shops":
                run_shop_imports(state)
                state["phase"] = "done"
                state["finished_at"] = _utcnow()
                _save_state(state)
                log.info("Full scan DONE: %s", state.get("counts"))
        except Exception as exc:
            log.exception("Phase %s failed (retry in 30s): %s", phase, exc)
            time.sleep(30)
            state = _load_state()

    progress = get_catalog_progress()
    log.info("Catalog progress: %s", progress)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Interrupted")
