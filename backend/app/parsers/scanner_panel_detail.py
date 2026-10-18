"""Rich per-shop scanner status for Panel3 «Сканери 9×» (no secrets)."""
from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.core.server_stats import _read_proc_cmdline, _read_proc_rss_kb
from app.models.models import Game, Offer
from app.parsers.scanner_control import (
    SHOP_SLUGS,
    list_scanner_statuses,
    pause_reason,
)
from app.parsers.shop_scan_queue import load_shop_progress, select_stale_game_ids_for_shop

# Seconds without progress update while unit is "active" → consider hung.
HUNG_AFTER_SEC = int(os.environ.get("SCANNER_HUNG_AFTER_SEC", "180"))
# Idle sleep can be 60s+; allow more slack before calling idle "stale".
IDLE_STALE_SEC = int(os.environ.get("SCANNER_IDLE_STALE_SEC", "300"))
AUTH_IDLE_SEC = int(os.environ.get("SCANNER_AUTH_IDLE_SEC", "700"))


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        s = str(raw).strip().replace("Z", "")
        if "." in s:
            s = s.split(".", 1)[0]
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _age_sec(dt: datetime | None, now: datetime) -> float | None:
    if dt is None:
        return None
    return max(0.0, (now - dt).total_seconds())


def _phase_ua(phase: str | None) -> str:
    mapping = {
        "running": "сканує зараз",
        "truncated": "цикл обрізано за часом",
        "idle": "очікування (немає застарілих)",
        "auth_failed": "блок авторизації",
        "auth_required": "потрібна авторизація",
        "paused": "пауза",
        "skipped": "пропущено (лок)",
        "failed": "помилка циклу",
        "error": "помилка",
        "fetching": "завантаження",
        "verifying": "верифікація",
        "writing": "запис у БД",
        "sleeping": "сон між циклами",
        "waiting_cooldown": "очікування cooldown",
    }
    if not phase:
        return "невідомо"
    return mapping.get(phase, phase)


def _human_status(
    *,
    is_active: str,
    sub_state: str,
    paused: bool,
    auth_blocker: str | None,
    phase: str | None,
    heartbeat_age_sec: float | None,
    last_check_status: str | None,
    verified_1h: int = 0,
    degraded_reason: str | None = None,
) -> dict[str, str]:
    """Return status code + labels for the big badge.

    Codes: WORKING | DEGRADED | AUTH_REQUIRED | RATE_LIMITED | PAUSED |
    STOPPED | ERROR | (legacy hung/waiting mapped for UI).
    Process active alone never implies WORKING.
    """
    phase = (phase or "").lower()
    active = (is_active or "").lower()
    status = (last_check_status or "").lower()

    if paused:
        return {
            "code": "paused",
            "status": "PAUSED",
            "label": "Пауза",
            "tone": "warn",
        }

    # Optional feed down but authorized fallback is verifying → DEGRADED, not AUTH.
    if degraded_reason and not auth_blocker and (verified_1h > 0 or phase in {"running", "truncated", "idle"}):
        return {
            "code": "degraded",
            "status": "DEGRADED",
            "label": "Деградовано",
            "tone": "warn",
        }

    # Stale auth_failed progress must not override live verifications / HTML fallback.
    stale_auth_phase = phase in {"auth_failed", "auth_required"} or status == "auth_failed"
    if auth_blocker:
        return {
            "code": "auth",
            "status": "AUTH_REQUIRED",
            "label": "Потрібна авторизація",
            "tone": "warn",
        }
    if stale_auth_phase and verified_1h == 0 and active in {"active", "activating", "reloading"}:
        # Process up but no recent verifies and progress still says auth — keep AUTH.
        return {
            "code": "auth",
            "status": "AUTH_REQUIRED",
            "label": "Потрібна авторизація",
            "tone": "warn",
        }

    if status == "rate_limited" or phase == "waiting_cooldown":
        return {
            "code": "rate_limited",
            "status": "RATE_LIMITED",
            "label": "Ліміт запитів",
            "tone": "warn",
        }
    if active == "failed" or phase in {"failed", "error"}:
        return {
            "code": "error",
            "status": "ERROR",
            "label": "Помилка",
            "tone": "bad",
        }
    if active in {"inactive", "dead", "failed"} or active == "":
        return {
            "code": "stopped",
            "status": "STOPPED",
            "label": "Зупинено",
            "tone": "bad",
        }
    if active not in {"active", "activating", "reloading"}:
        return {
            "code": "stopped",
            "status": "STOPPED",
            "label": "Зупинено",
            "tone": "bad",
        }

    age = heartbeat_age_sec
    if phase == "running" and age is not None and age > HUNG_AFTER_SEC:
        return {
            "code": "hung",
            "status": "ERROR",
            "label": "Завис?",
            "tone": "bad",
        }
    if phase == "idle" and age is not None and age > IDLE_STALE_SEC:
        return {
            "code": "hung",
            "status": "ERROR",
            "label": "Завис? (довге мовчання)",
            "tone": "bad",
        }
    if degraded_reason:
        return {
            "code": "degraded",
            "status": "DEGRADED",
            "label": "Деградовано",
            "tone": "warn",
        }
    if phase in {"running", "truncated"}:
        return {
            "code": "working",
            "status": "WORKING",
            "label": "Працює",
            "tone": "ok",
        }
    if phase == "idle":
        return {
            "code": "waiting",
            "status": "WORKING",
            "label": "Працює · очікує чергу",
            "tone": "ok",
        }
    if sub_state == "running" or verified_1h > 0:
        return {
            "code": "working",
            "status": "WORKING",
            "label": "Працює",
            "tone": "ok",
        }
    return {
        "code": "working",
        "status": "WORKING",
        "label": "Працює",
        "tone": "ok",
    }


def _shop_db_stats(db: Session, shops: list[str], now: datetime) -> dict[str, dict[str, Any]]:
    """Batch verified counts + recent attempt status breakdown (no secrets)."""
    out: dict[str, dict[str, Any]] = {
        s: {
            "verified_1h": 0,
            "verified_24h": 0,
            "attempts_1h": 0,
            "success_pct_1h": None,
            "http_errors_1h": {"403": 0, "429": 0, "5xx": 0, "other": 0},
            "status_counts_1h": {},
            "last_verified_at": None,
            "last_attempt_at": None,
            "last_check_status": None,
            "last_game_id": None,
        }
        for s in shops
    }
    if not shops:
        return out

    cut_1h = now - timedelta(hours=1)
    cut_24h = now - timedelta(hours=24)

    rows_1h = (
        db.query(Offer.shop_name, func.count(Offer.id))
        .filter(
            Offer.shop_name.in_(shops),
            Offer.last_check_status == "verified",
            Offer.last_verified_at.isnot(None),
            Offer.last_verified_at >= cut_1h,
        )
        .group_by(Offer.shop_name)
        .all()
    )
    for shop, cnt in rows_1h:
        out[str(shop)]["verified_1h"] = int(cnt)

    rows_24h = (
        db.query(Offer.shop_name, func.count(Offer.id))
        .filter(
            Offer.shop_name.in_(shops),
            Offer.last_check_status == "verified",
            Offer.last_verified_at.isnot(None),
            Offer.last_verified_at >= cut_24h,
        )
        .group_by(Offer.shop_name)
        .all()
    )
    for shop, cnt in rows_24h:
        out[str(shop)]["verified_24h"] = int(cnt)

    # Status breakdown for last hour of attempts.
    status_rows = (
        db.query(Offer.shop_name, Offer.last_check_status, func.count(Offer.id))
        .filter(
            Offer.shop_name.in_(shops),
            Offer.last_attempt_at.isnot(None),
            Offer.last_attempt_at >= cut_1h,
        )
        .group_by(Offer.shop_name, Offer.last_check_status)
        .all()
    )
    for shop, status, cnt in status_rows:
        key = str(status or "unknown")
        bucket = out[str(shop)]["status_counts_1h"]
        bucket[key] = int(cnt)
        out[str(shop)]["attempts_1h"] += int(cnt)
        low = key.lower()
        http = out[str(shop)]["http_errors_1h"]
        if "403" in low or low in {"forbidden", "blocked"}:
            http["403"] += int(cnt)
        elif "429" in low or "rate" in low:
            http["429"] += int(cnt)
        elif any(x in low for x in ("500", "502", "503", "504", "5xx", "server_error")):
            http["5xx"] += int(cnt)
        elif low not in {"verified", "ok", "unchanged", "same_price", "none", "unknown", ""}:
            if "error" in low or "fail" in low or "timeout" in low:
                http["other"] += int(cnt)

    for shop, data in out.items():
        attempts = int(data["attempts_1h"] or 0)
        verified = int(data["verified_1h"] or 0)
        if attempts > 0:
            data["success_pct_1h"] = round(100.0 * verified / attempts, 1)

    # Latest attempt per shop (one query, then pick max in Python).
    latest = (
        db.query(
            Offer.shop_name,
            Offer.game_id,
            Offer.last_attempt_at,
            Offer.last_verified_at,
            Offer.last_check_status,
        )
        .filter(Offer.shop_name.in_(shops), Offer.last_attempt_at.isnot(None))
        .order_by(Offer.last_attempt_at.desc())
        .limit(200)
        .all()
    )
    seen: set[str] = set()
    for shop, game_id, last_attempt, last_verified, status in latest:
        s = str(shop)
        if s in seen:
            continue
        seen.add(s)
        if s not in out:
            continue
        out[s]["last_game_id"] = int(game_id) if game_id is not None else None
        out[s]["last_attempt_at"] = last_attempt.isoformat(sep=" ") if last_attempt else None
        out[s]["last_verified_at"] = last_verified.isoformat(sep=" ") if last_verified else None
        out[s]["last_check_status"] = status

    return out


def _game_briefs(db: Session, game_ids: list[int]) -> dict[int, dict[str, Any]]:
    ids = [int(g) for g in game_ids if g]
    if not ids:
        return {}
    rows = db.query(Game.id, Game.title, Game.slug).filter(Game.id.in_(ids)).all()
    return {
        int(gid): {"id": int(gid), "title": title, "slug": slug}
        for gid, title, slug in rows
    }


def _proc_stats(pid: int) -> dict[str, Any]:
    if not pid or pid <= 0:
        return {"pid": 0, "mem_mb": None, "cmdline": ""}
    rss = _read_proc_rss_kb(pid)
    return {
        "pid": pid,
        "mem_mb": round(rss / 1024, 1) if rss else None,
        "cmdline": (_read_proc_cmdline(pid) or "")[:120],
    }


def _queue_estimate(db: Session, shop: str) -> dict[str, Any]:
    """Capped stale-queue peek — cheap enough for admin poll."""
    try:
        ids = select_stale_game_ids_for_shop(db, shop, limit=51, after_game_id=0)
    except Exception as exc:
        return {"queue_left": None, "queue_capped": False, "queue_error": str(exc)[:120]}
    n = len(ids)
    return {
        "queue_left": 50 if n > 50 else n,
        "queue_capped": n > 50,
        "queue_error": None,
    }


def enrich_scanner_rows(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    base_rows = list_scanner_statuses()
    shops = [r.get("shop") or "" for r in base_rows if r.get("shop")]
    db_stats = _shop_db_stats(db, shops, now)

    cursor_ids: list[int] = []
    for r in base_rows:
        shop = r.get("shop") or ""
        prog = load_shop_progress(shop) if shop else {}
        cid = prog.get("cursor_game_id")
        if cid:
            cursor_ids.append(int(cid))
        last_gid = (db_stats.get(shop) or {}).get("last_game_id")
        if last_gid:
            cursor_ids.append(int(last_gid))
    games = _game_briefs(db, cursor_ids)

    from app.core.offer_verification import shop_auth_blocker, shop_data_source_status

    enriched: list[dict[str, Any]] = []
    really_scanning = 0

    for st in base_rows:
        shop = st.get("shop") or ""
        slug = st.get("slug") or ""
        prog = load_shop_progress(shop) if shop else {}
        auth = shop_auth_blocker(shop) if shop else None
        ds = shop_data_source_status(shop) if shop else {}
        stats = db_stats.get(shop) or {}
        verified_1h = int(stats.get("verified_1h") or 0)

        updated_at = _parse_iso(prog.get("updated_at"))
        batch_started = _parse_iso(prog.get("batch_started_at"))
        heartbeat_src = updated_at or batch_started
        if updated_at and batch_started:
            heartbeat_src = max(updated_at, batch_started)
        heartbeat_age = _age_sec(heartbeat_src, now)

        phase = prog.get("phase")
        human = _human_status(
            is_active=str(st.get("is_active") or ""),
            sub_state=str(st.get("sub_state") or ""),
            paused=bool(st.get("paused")),
            auth_blocker=auth,
            phase=str(phase) if phase is not None else None,
            heartbeat_age_sec=heartbeat_age,
            last_check_status=str(
                prog.get("last_check_status") or stats.get("last_check_status") or ""
            ),
            verified_1h=verified_1h,
            degraded_reason=ds.get("degraded_reason"),
        )

        pid = int(st.get("main_pid") or 0)
        proc = _proc_stats(pid)
        # Skip heavy queue peek when shop already reports empty stale set.
        need_queue = bool(
            shop
            and human["code"] in {"working", "waiting", "hung", "degraded"}
            and not (
                (phase or "") == "idle"
                and str(prog.get("message") or "") == "no_stale_games"
            )
        )
        if need_queue:
            queue = _queue_estimate(db, shop)
        elif (phase or "") == "idle" and str(prog.get("message") or "") == "no_stale_games":
            queue = {"queue_left": 0, "queue_capped": False, "queue_error": None}
        else:
            queue = {"queue_left": None, "queue_capped": False, "queue_error": None}

        cursor_id = int(prog.get("cursor_game_id") or 0) or None
        last_game_id = stats.get("last_game_id") or cursor_id
        current_game = games.get(int(cursor_id)) if cursor_id else None
        last_game = games.get(int(last_game_id)) if last_game_id else None

        checked = int(prog.get("checked") or 0)
        verified_total = int(prog.get("verified") or 0)
        last_batch_size = int(prog.get("last_batch_size") or 0)
        last_batch_verified = int(prog.get("last_batch_verified") or 0)
        last_batch_errors = int(prog.get("last_batch_errors") or 0)
        last_batch_sec = float(prog.get("last_batch_sec") or 0.0)
        vpm = prog.get("verified_per_min")
        games_per_min = None
        if last_batch_sec and last_batch_size:
            games_per_min = round(60.0 * last_batch_size / last_batch_sec, 2)

        # ETA from capped queue + games/min (best-effort).
        eta_min = None
        qleft = queue.get("queue_left")
        if isinstance(qleft, int) and games_per_min and games_per_min > 0 and not queue.get("queue_capped"):
            eta_min = round(qleft / games_per_min, 1)

        is_really = human["code"] == "working" and (phase or "") in {"running", "truncated"}
        if is_really and heartbeat_age is not None and heartbeat_age < HUNG_AFTER_SEC:
            really_scanning += 1
        elif human["code"] == "working" and stats.get("verified_1h", 0) > 0 and (
            heartbeat_age is None or heartbeat_age < HUNG_AFTER_SEC
        ):
            # Active process recently verifying even if phase flipped to idle mid-poll.
            if (phase or "") == "running":
                really_scanning += 1

        # Safe last error (never dump tokens/keys).
        last_error = None
        msg = (prog.get("message") or "").strip()
        if human["code"] in {"auth", "error", "hung"}:
            last_error = (auth or msg or stats.get("last_check_status") or "")[:200] or None
        elif msg and msg not in {"no_stale_games"}:
            last_error = msg[:200]

        # Uptime from systemd ActiveEnterTimestamp (best-effort parse).
        active_enter = st.get("active_enter") or ""
        uptime_sec = None
        # Format like: "Thu 2026-10-15 21:10:21 CEST"
        try:
            parts = active_enter.replace("  ", " ").strip().split(" ")
            if len(parts) >= 3:
                # date time without weekday/tz for fromisoformat-ish
                date_s, time_s = parts[1], parts[2]
                entered = datetime.fromisoformat(f"{date_s}T{time_s}")
                uptime_sec = _age_sec(entered, now)
        except Exception:
            uptime_sec = None

        batch_success_pct = None
        if last_batch_size > 0:
            batch_success_pct = round(100.0 * last_batch_verified / last_batch_size, 1)

        process_status = str(st.get("is_active") or "unknown")
        enriched.append(
            {
                **st,
                "auth_blocker": auth,
                "human_status": human["label"],
                "human_code": human["code"],
                "human_status_code": human.get("status") or human["code"].upper(),
                "human_tone": human["tone"],
                "process_status": process_status,
                "data_source": {
                    "primary": ds.get("primary"),
                    "fallback": ds.get("fallback"),
                    "block_scan": bool(ds.get("block_scan")),
                    "block_reason": ds.get("block_reason"),
                    "degraded_reason": ds.get("degraded_reason"),
                    "owner_action": ds.get("owner_action"),
                    "algolia_ok": ds.get("algolia_ok"),
                    "feed_ok": ds.get("feed_ok"),
                    "html_fallback": ds.get("html_fallback"),
                },
                "really_scanning": bool(
                    human["code"] in {"working", "degraded"}
                    and (phase or "") in {"running", "truncated"}
                    and (heartbeat_age is None or heartbeat_age < HUNG_AFTER_SEC)
                ),
                "heartbeat_age_sec": round(heartbeat_age, 1) if heartbeat_age is not None else None,
                "heartbeat_stale": bool(
                    heartbeat_age is not None
                    and heartbeat_age
                    > (AUTH_IDLE_SEC if human["code"] == "auth" else HUNG_AFTER_SEC)
                ),
                "uptime_sec": round(uptime_sec, 0) if uptime_sec is not None else None,
                "proc": proc,
                "activity": {
                    "phase": phase,
                    "phase_ua": _phase_ua(str(phase) if phase is not None else None),
                    "method": prog.get("method"),
                    "message": (prog.get("message") or "")[:200] or None,
                    "cursor_game_id": cursor_id,
                    "current_game": current_game,
                    "last_game": last_game,
                    "batch_started_at": prog.get("batch_started_at"),
                    "cycle_finished_at": prog.get("cycle_finished_at"),
                    "updated_at": prog.get("updated_at"),
                },
                "throughput": {
                    "verified_total_session": verified_total,
                    "checked_total_session": checked,
                    "attempts_total_session": checked,
                    "verified_1h": stats.get("verified_1h", 0),
                    "verified_24h": stats.get("verified_24h", 0),
                    "verified_per_min": vpm,
                    "games_per_min": games_per_min,
                    "success_pct_1h": stats.get("success_pct_1h"),
                    "attempts_1h": stats.get("attempts_1h", 0),
                    "http_ok_note": "attempts_1h = offer rows touched; verified_1h = confirmed prices",
                },
                "last_batch": {
                    "size": last_batch_size,
                    "verified": last_batch_verified,
                    "updated": int(prog.get("last_batch_updated") or 0),
                    "errors": last_batch_errors,
                    "sec": last_batch_sec,
                    "success_pct": batch_success_pct,
                },
                "queue": {
                    "left": queue.get("queue_left"),
                    "capped": bool(queue.get("queue_capped")),
                    "eta_min": eta_min,
                },
                "last_verified_at": stats.get("last_verified_at") or prog.get("updated_at"),
                "last_attempt_at": stats.get("last_attempt_at"),
                "last_check_status": stats.get("last_check_status")
                or prog.get("last_check_status"),
                "last_error": last_error,
                "http_errors_1h": stats.get("http_errors_1h") or {},
                "status_counts_1h": stats.get("status_counts_1h") or {},
                # Keep legacy nested progress for older UI bits.
                "progress": {
                    "phase": phase,
                    "verified": verified_total,
                    "last_batch_verified": last_batch_verified,
                    "verified_per_min": vpm,
                    "cursor": cursor_id,
                    "message": prog.get("message"),
                    "updated_at": prog.get("updated_at"),
                    "checked": checked,
                    "last_batch_size": last_batch_size,
                    "last_batch_errors": last_batch_errors,
                    "last_batch_sec": last_batch_sec,
                },
            }
        )

    # Recount really_scanning from enriched flags for consistency.
    really_scanning = sum(1 for r in enriched if r.get("really_scanning"))
    workingish = sum(
        1 for r in enriched if r.get("human_code") in {"working", "waiting", "degraded"}
    )
    auth_n = sum(1 for r in enriched if r.get("human_code") == "auth")
    degraded_n = sum(1 for r in enriched if r.get("human_code") == "degraded")
    paused_n = sum(1 for r in enriched if r.get("human_code") == "paused")
    hung_n = sum(1 for r in enriched if r.get("human_code") == "hung")
    stopped_n = sum(1 for r in enriched if r.get("human_code") in {"stopped", "error"})

    summary_tone = "ok" if really_scanning >= 1 else ("warn" if workingish else "bad")
    if hung_n or stopped_n >= 3:
        summary_tone = "bad" if really_scanning == 0 else "warn"

    return {
        "ok": True,
        "slugs": list(SHOP_SLUGS.keys()),
        "global_pause_reason": pause_reason(),
        "snapshot_at": now.isoformat(sep=" ") + "Z",
        "summary": {
            "total": len(enriched),
            "really_scanning": really_scanning,
            "working_or_waiting": workingish,
            "auth_blocked": auth_n,
            "degraded": degraded_n,
            "paused": paused_n,
            "hung": hung_n,
            "stopped_or_error": stopped_n,
            "tone": summary_tone,
            "headline_ua": f"{really_scanning} з {len(enriched)} реально сканують зараз",
            "detail_ua": (
                f"у роботі/очікуванні {workingish} · деградовано {degraded_n} · "
                f"авторизація {auth_n} · пауза {paused_n} · зависли {hung_n} · "
                f"зупинені/помилка {stopped_n}"
            ),
        },
        "scanners": enriched,
        "thresholds": {
            "hung_after_sec": HUNG_AFTER_SEC,
            "idle_stale_sec": IDLE_STALE_SEC,
        },
    }
