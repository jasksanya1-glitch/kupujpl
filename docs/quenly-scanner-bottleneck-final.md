# Quenly — Scanner Bottleneck & Price Coverage Fix (Final)

**Date:** 2026-10-18  
**Production:** `159.195.86.11` / `https://kupujpl.pl/games/`  
**Theme:** Cozy Orange (unchanged)  
**Price Engine:** V2 — **not loosened**  
**Baseline:** `docs/quenly-scanner-throughput-recovery.md` (confirmed **13.87%**)

---

## Verdict

**STEAM THROUGHPUT BOTTLENECK FIXED — COVERAGE RISING — PENDING LONG-TERM VERIFICATION**

Root cause of Steam ~39 verified/hour (vs theoretical ~2.5 HTTP RPS) was **not** RPS headroom. It was:

1. **Popularity-ordered queue + `after_game_id=cursor` paging** → after high-id batches, selection returned empty → `no_stale_games`.
2. **Empty-queue idle = max(idle, 60s)** → scanners slept a minute after each false empty.

Canary (no RPS increase): Steam batches **60 games / ~24s / ~56 verified**, idle **8s** → metrics hour bucket **~224 verified / ~2 min wall** → **~2 200+/h** extrapolated from 15‑minute window (567 Steam verifies in 15m).

Confirmed paid coverage **13.87% → 21.37%** (1 508 → **2 225**) during this pass.  
**Do not call this sustained** until 48–72h of hourly snapshots confirm the rate holds as the backlog ages.

---

## 1. Main bottlenecks (where time went)

| Bottleneck | Shop | Symptom | Fix |
|------------|------|---------|-----|
| False `no_stale_games` + 60s idle | **Steam** (all shops) | Cursor skipped popularity-ordered stale set | `after_game_id=0`; empty idle 5–15s |
| HTTP vs verified confusion | Steam | RPS ≈ request rate; verified/h starved by idle | Metrics separate `http_requests` vs `verified` |
| Auth / feed dead | **Fanatical** | Awin FID invalid → honest `auth_failed` | Document FID dependency; no fake stamps |
| Parser/HTML errors | **G2A** | 169 `error` vs 72 `verified` / 24h; 403 cooldown | Status stays `error` (not silent success) |
| Algolia / feed flakiness | CDKeys / Kinguin | Lower v/h than IG | Prior unblocks kept; no credential invention |

**Steam gap explained:** At RPS 2.5, a 60-game batch needs ≥24s of HTTP. Observed ~24s with ~56 verifies → HTTP path is healthy. Wall-clock verified/h was killed by **idle after false empty queues**, not by Steam API latency.

---

## 2. Actual scanner speed (canary)

### Steam (post-fix, first ~4 cycles)

| Metric | Value |
|--------|-------|
| Batch | 60 attempted, **56 verified**, ~24s |
| Idle between batches | **8s** (was 60s on empty) |
| Metrics hour bucket | attempted 240, verified **224**, idle_sec 32, batch_sec 98 |
| `verified_per_hour_est` (batch-only) | ~8 200 |
| Wall estimate incl. idle | ~6 000+/h while backlog exists |
| 15‑minute live window | **567** Steam verifies → **~2 268/h** |
| Pre-fix (throughput report) | **~39/h** |

### Other shops (15‑minute window → rough /h)

| Shop | v15m | ~v/h | Notes |
|------|------|------|-------|
| Instant Gaming | 55 | ~220 | Healthy |
| Epic | 46 | ~184 | |
| Gamivo | 43 | ~172 | |
| GOG | 38 | ~152 | |
| G2A | 39 | ~156 | High `error` share remains |
| Kinguin | 34 | ~136 | |
| CDKeys | 34 | ~136 | |
| Fanatical | 0 | 0 | Awin FID dead |

---

## 3. Coverage before / after

| Metric | Before (throughput recovery) | After bottleneck canary |
|--------|------------------------------|-------------------------|
| Paid confirmed (PE V2) | **1 508 (13.87%)** | **2 225 (21.37%)** of 10 414 paid |
| Tier A confirmed | — | **2 065 / 5 010 (41.22%)** |
| Tier B confirmed | — | **2 / 5 (40%)** |
| Tier C confirmed | — | **158 / 5 399 (2.93%)** |
| F2P excluded from paid coverage | — | **461** |
| Games with any verification 24h | 1 998 | **2 598** |

Confirmed ≠ “any check”. Coverage monitor / snapshots enforce that split.

---

## 4. Tier A/B/C fairness

- Default `select_stale_game_ids_for_shop(..., tier_a_only=False)`.
- Batch mix: A 55% / B 25% / C 20% + starvation every Nth.
- Cursor paging by `max(game_id)` **disabled** (`cursor_mode=disabled_popularity_order`).
- Tests: `tests/test_queue_fairness.py` (Tier C appears in mixed batch).

---

## 5. Verification safety

| Rule | Status |
|------|--------|
| `live_fetch=True` → may `record_verified_price` | OK |
| `live_fetch=False` / replay → no freshness bump | OK (`test_out_of_order_verification`, upsert stamps) |
| Out-of-order `observed_at` refused | OK |
| F2P: paid marketplace offers never become confirmed best | **Hardened** in `price_engine._classify_offer_row` |
| Cached Fanatical feed cannot stamp verified | Blocked via `shop_auth_blocker` |

---

## 6. Monitoring

- `/api/admin/coverage` + `POST /api/admin/coverage/snapshot`
- Hourly + daily JSON under `backend/tmp/coverage_snapshots/` (+ `hourly/`)
- systemd: `kupujpl-coverage-snapshot.timer` (hourly)
- Per-shop metrics: `backend/tmp/scanner_metrics/*.json`  
  (HTTP reqs, verified, idle, rate-limit waits, batch_sec, unchanged %)

**PENDING LONG-TERM VERIFICATION:** keep timer running 48–72h; compare hourly `paid_confirmed_pct` and Steam `verified_1h`.

---

## 7. Weak shops — root causes

| Shop | Root cause | Dependency / next step |
|------|------------|------------------------|
| **G2A** | Live HTML/API errors (403 cooldown in `g2a_parser`); errors recorded as `error`, not verified | Tune delay; do not mask as success |
| **Kinguin** | Prior HTML fallback when Awin feed fails | Keep; monitor error rate |
| **GOG / Epic** | Official APIs; limited by RPS + stale mix | Idle/cursor fix helps refill |
| **CDKeys** | Algolia key refresh flaky historically | Auto-refresh path unchanged |
| **Fanatical** | `AWIN_FEED_FID_FANATICAL` → 404 / invalid | **Need valid Awin FID** (do not invent). Env keys present: `AWIN_FEED_FID_FANATICAL`, `AWIN_FEED_MERCHANT_FANATICAL`, `AWIN_DATAFEED_API_KEY` |

---

## 8. Tests

| Suite | Result |
|-------|--------|
| Queue fairness | PASS |
| Out-of-order / upsert stamps | PASS |
| PE V2 (`test_price_engine`, F2P, promocje, SEO landings) | PASS |
| Scanner reliability / optimization | PASS |
| Per-file unit suite (excl. live SSR during outage) | PASS |
| Live SSR (`test_ssr_bot_status`) | PASS after `worth_buy.py` deploy |
| Playwright catalog | **Not present** as `test_playwright_catalog.py` in repo |
| `store_class` schema test | Residual FAIL (schema field missing — out of scanner scope) |

---

## 9. Deploy / backup / rollback

| Item | Path |
|------|------|
| Backup | `/opt/kupujpl-games/backups/pre-bottleneck-fix-20261018-040237/` |
| SQLite backup | `…/database.db` (111 MB) |
| Code backups | `backend__app__parsers__*.py`, `backend__app__core__*.py` |
| Whitelist deployed | `shop_scan_queue.py`, `independent_scanner.py`, `steam_catalog.py`, `scanner_metrics.py`, `coverage_monitor.py`, `offer_verification.py`, `price_engine.py`, `scanner_admin_routes.py`, **`worth_buy.py`** (SSR 500 hotfix) |
| Steam canary unit drop-in | `SCAN_BATCH_SIZE=60`, `SCAN_IDLE_SEC=8`, deadline 360 |
| Rollback | Restore files from backup dir → `systemctl restart kupujpl-games kupujpl-scanner@steam` (+ other scanners) |

### Production incident during deploy

Restarting `kupujpl-games` exposed pre-existing mismatch: `main.py` passed `history_points=` but prod `worth_buy.py` lacked the parameter → **`/gra/*` HTTP 500**. Fixed by deploying current `worth_buy.py`. Public checks: **200**.

---

## 10. CPU / RAM / SQLite

| Signal | During canary |
|--------|----------------|
| Load average | ~0.6–1.0 on 8 vCPU (acceptable) |
| RAM | ~2 GB used / 15 GB |
| SQLite | WAL; no lock storm observed |
| Steam scanner | `active` continuous batches |

---

## 11. Git commits (local)

| Commit | Message |
|--------|---------|
| `594c753` | Fix Steam scanner idle/cursor starvation and raise verified/hour. |
| Prior | `65a8772`, `5a4315e`, `d63106e` (throughput / coverage series) |

---

## 12. Residual limitations

1. **Fanatical** remains 0 until a valid Awin FID is supplied.  
2. **G2A** high error ratio — antibot/403; no bypass.  
3. Tier C coverage still low (~3%) — expected until multi-day fair queue runs.  
4. Steam batch `verified_per_hour_est` is **batch-active** math; wall-clock falls as stale backlog shrinks.  
5. **PENDING LONG-TERM VERIFICATION (48–72h)** before claiming sustained coverage.

---

## Success criteria checklist

| Criterion | Status |
|-----------|--------|
| Increase successful verifications/hour without lowering accuracy | **Met (Steam canary)** |
| No infinite Tier B/C starvation | **Met (mix + tests)** |
| Scanners stable, VPS not overloaded | **Met (canary load)** |
| PE V2 correct; no fake prices / timestamp healing | **Met** |
| Max credible coverage of popular paid games | **Improved; long-term PENDING** |
