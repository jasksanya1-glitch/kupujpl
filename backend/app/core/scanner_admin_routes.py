"""Panel3 admin API for independent per-shop scanners (9× systemd workers)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import BASE_DIR, get_db
from app.core.panel3_auth import (
    panel3_gate_ok,
    require_panel3_admin,
    require_panel3_csrf,
)
from app.parsers.scanner_control import (
    SHOP_SLUGS,
    restart_scanner,
    set_paused,
    start_scanner,
    stop_scanner,
)
from app.parsers.scanner_panel_detail import enrich_scanner_rows

router = APIRouter(tags=["panel3-scanners"])

_STATIC_DIR = os.path.join(str(BASE_DIR), "app", "static")


def _static_page(name: str):
    path = os.path.join(_STATIC_DIR, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(path)


def _parse_slug(body: dict | None) -> str:
    raw = str((body or {}).get("slug") or "all").strip().lower()
    if raw in {"", "all", "*"}:
        return "all"
    if raw not in SHOP_SLUGS:
        raise HTTPException(status_code=400, detail=f"Unknown scanner slug: {raw}")
    return raw


async def _json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


@router.get("/panel/scanners")
def panel_scanners_page(request: Request):
    """Standalone scanners dashboard (also linked from Panel3)."""
    if not panel3_gate_ok(request):
        return RedirectResponse(url="/games/panel3", status_code=303)
    require_panel3_admin(request)
    return _static_page("panel_scanners.html")


@router.get("/api/admin/scanners/status")
def admin_scanners_status(request: Request, db: Session = Depends(get_db)):
    require_panel3_admin(request)
    return enrich_scanner_rows(db)


@router.post("/api/admin/scanners/pause")
async def admin_scanners_pause(request: Request):
    require_panel3_admin(request)
    require_panel3_csrf(request)
    slug = _parse_slug(await _json_body(request))
    out = set_paused(None if slug == "all" else slug, True, reason="panel3")
    return {"ok": True, **out}


@router.post("/api/admin/scanners/resume")
async def admin_scanners_resume(request: Request):
    require_panel3_admin(request)
    require_panel3_csrf(request)
    slug = _parse_slug(await _json_body(request))
    out = set_paused(None if slug == "all" else slug, False, reason="panel3")
    return {"ok": True, **out}


@router.post("/api/admin/scanners/start")
async def admin_scanners_start(request: Request):
    require_panel3_admin(request)
    require_panel3_csrf(request)
    slug = _parse_slug(await _json_body(request))
    if slug == "all":
        results = [start_scanner(s) for s in SHOP_SLUGS]
        return {"ok": all(r.get("ok") for r in results), "results": results}
    return {"ok": True, **start_scanner(slug)}


@router.post("/api/admin/scanners/stop")
async def admin_scanners_stop(request: Request):
    require_panel3_admin(request)
    require_panel3_csrf(request)
    slug = _parse_slug(await _json_body(request))
    if slug == "all":
        results = [stop_scanner(s) for s in SHOP_SLUGS]
        return {"ok": all(r.get("ok") for r in results), "results": results}
    return {"ok": True, **stop_scanner(slug)}


@router.post("/api/admin/scanners/restart")
async def admin_scanners_restart(request: Request):
    require_panel3_admin(request)
    require_panel3_csrf(request)
    slug = _parse_slug(await _json_body(request))
    if slug == "all":
        results = [restart_scanner(s) for s in SHOP_SLUGS]
        return {"ok": all(r.get("ok") for r in results), "results": results}
    return {"ok": True, **restart_scanner(slug)}


@router.get("/api/admin/coverage")
def admin_coverage_snapshot(request: Request, db: Session = Depends(get_db)):
    """Live catalog coverage + per-shop verify rates (panel3 admin only)."""
    require_panel3_admin(request)
    from app.core.coverage_monitor import build_coverage_snapshot

    return build_coverage_snapshot(db)


@router.post("/api/admin/coverage/snapshot")
def admin_coverage_save(request: Request, db: Session = Depends(get_db)):
    require_panel3_admin(request)
    require_panel3_csrf(request)
    from app.core.coverage_monitor import save_coverage_snapshot

    return save_coverage_snapshot(db)


@router.get("/api/admin/coverage/compare")
def admin_coverage_compare(
    request: Request,
    day_a: str,
    day_b: str | None = None,
    db: Session = Depends(get_db),
):
    require_panel3_admin(request)
    from app.core.coverage_monitor import compare_coverage_days

    return compare_coverage_days(db, day_a, day_b)
