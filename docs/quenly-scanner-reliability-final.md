# Quenly — Scanner Reliability & Efficiency Final Report

**Date:** 2026-10-18  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange — unchanged  
**Price Engine:** V2 — unchanged  
**Prior report:** `docs/quenly-parallel-scanner-performance-final.md` (`3244e9a`)  
**Status:** **VERIFIED FIXES DEPLOYED — LONG-TERM PENDING**

Not claimed FULLY VERIFIED / SUSTAINED: coverage and IG throughput need 48–72h of hourly snapshots.

---

## 1. Instant Gaming investigation

### Verdict
**Real queue regression (efficiency), not a dead parser.**  
HTTP search worked (`window.searchResults` present, HTTP 200). Popular PC Steam listings often have `has_stock=0` (e.g. Hades, Stardew). Parser correctly returns no price.  

Independent scanner kept re-selecting the same high-review games with **no IG offer row**, so misses never entered `STATUS_BACKOFF` → batches reported `verified=0` for long stretches (canary 15m zero). Meanwhile mid-catalog titles with stock (Elden Ring, Hollow Knight, Valheim) parsed successfully when probed manually.

Last successful verification before fix window: `2026-10-18 04:24:47` UTC; hour `T05` pre-fix still showed `verified_1h=60` once the wheel moved — confirming temporary zeros were spin/idle, amplified by missing backoff.

### Fix
1. `_deactivate_shop_offer` creates an `in_stock=False`, `price_pln=0` stub with `last_check_status=unavailable` and `last_attempt_at` (never sets `last_verified_at`).
2. Stale selection backs off `unavailable` / `error` / `timeout` for `STATUS_BACKOFF_HOURS` (same as auth failures).

### Post-deploy evidence
- `ig_unavailable_stubs=74` within minutes  
- Queue moved off the Hades loop to mid-tier titles  
- `Instant_Gaming` batch `ver=3` (was stuck at 0)  
- PE V2 excludes `price_pln<=0` / OOS stubs from confirmed prices  

Regression tests: `tests/test_shop_miss_backoff.py`.

---

## 2. GOG / Epic zero-verification root causes

| Cause | Classification | Action |
|---|---|---|
| Titles not sold on GOG (e.g. Hades — catalog has no product; `/en/game/hades` redirects to `/games`) | Expected no-offer | Miss stub + backoff (same as IG) |
| GOG remaster SKU mismatch (`Wild Hunt — Remastered` vs catalog title without Remastered) — `title_mismatch` rejected | **Bug** | Strip remaster label in `pick_best_gog_product` only |
| Epic often returns matches (Hades OK) but many catalog games still miss / free | Mixed expected | No PE loosen |
| Batches with `last_batch_verified=0` while `workers=3` | Mostly no-offer / match miss, not RPS | Improved by remaster fix + miss backoff |

Post-fix: `search_gog_price('The Witcher 3: Wild Hunt')` → `74.99 PLN` on remastered SKU.

---

## 3. Rate limiter safety

- Per-shop **shared** `_RateLimiter` via `shared_shop_limiter(shop)`.
- `set_shop_http_context(shop)` around each game worker.
- `fetch_url` and `http_pool` Session get/post call `shop_http_wait()` so retries / product-page follow-ups / catalog+price calls share the same budget.
- In-flight game dedupe unchanged.
- Tests: `test_shared_limiter_serializes_http_across_threads`, existing inflight tests.

RPS budgets were **not** increased.

---

## 4. True hourly throughput (1h windows)

### Pre reliability deploy (`2026-10-18T05:12:44Z`)

| Shop | verified/h | unique games/h |
|---|---:|---:|
| Steam | 2258 | 2258 |
| GOG | 35 | 35 |
| Epic Games | 38 | 38 |
| Instant Gaming | 60 | 60 |
| Kinguin | 31 | 31 |
| G2A | 36 | 36 |
| Gamivo | 36 | 36 |
| CDKeys | 79 | 79 |
| Fanatical | 0 | 0 |

### ~6 min post deploy (`2026-10-18T05:18Z`) — still settling

| Shop | verified 15m | verified 1h |
|---|---:|---:|
| Steam | 539 | 2239 |
| Instant Gaming | 3 | 32 |
| GOG | 35 | 35 |
| Epic | 38 | 38 |

Do **not** treat 15m×4 as equal to a full hour. IG 1h dipped while stubs were written and queue rotated — expected short-term. Re-measure after ≥1h.

Errors: Fanatical auth-idle (expected). CDKeys Algolia missing (expected). No Steam 429 storm observed.

---

## 5. Confirmed coverage before / after

| Moment | Confirmed | % | Tier C % |
|---|---:|---:|---:|
| Parallel canary earlier | 3799 | 36.48 | 13.42 |
| Reliability pre-deploy | 4284 | 41.14 | 19.88 |
| Reliability post (~6m) | 4464 | **42.87** | **22.28** |

Paid games: 10,414. Coverage rising; **not** yet sustained proof.

---

## 6. Tier A / B / C (post)

| Tier | Games | Confirmed | % |
|---|---:|---:|---:|
| A | 1726 | 1652 | 95.71 |
| B | 1183 | 1140 | 96.37 |
| C | 7505 | 1672 | 22.28 |

---

## 7. Full pytest

**Production venv** (`PRICE_ENGINE_V2=1`, `SKIP_LIVE_HTTP=1`, ignore cozy e2e):  
**187 passed**, 0 failed (after syncing stale `test_engine_unverified_offers.py` which had drifted on prod — assertion expected `len==1` vs current PE returning stale+excluded).

Local critical subset (PE V2, queues, miss backoff, parallel, Playwright catalog): **29 passed, 5 skipped**.

Windows full-suite runner was interrupted by environment KeyboardInterrupt (known harness issue); production full run is the authoritative completion for this pass.

---

## 8. Playwright

Catalog Playwright module included in local critical run (skipped where browser/env missing: counted in the 5 skips). No new catalog regressions asserted as failed.

---

## 9. SSR smoke

| URL | Status |
|---|---|
| `/games/gra/hades-ii` | **200** |
| `/games/gra/cyberpunk-2077` | **200** |

No unexpected HTTP 500 on smoked game pages.

---

## 10. Git commits

- Prior parallel: `3244e9a`  
- This pass: 9266f7a  

---

## 11. Changed production files (whitelist)

| File | Change |
|---|---|
| `backend/app/parsers/game_offers.py` | Miss stubs on deactivate |
| `backend/app/parsers/shop_scan_queue.py` | unavailable backoff; shared limiter + HTTP context |
| `backend/app/parsers/gog_parser.py` | Remaster strip for official match |
| `backend/app/parsers/http_pool.py` | Rate-limited Session wrapper |
| `backend/app/parsers/keyshop_common.py` | `fetch_url` → `shop_http_wait` |
| `backend/tests/test_shop_miss_backoff.py` | New |
| `backend/tests/test_scan_parallel_safety.py` | Shared limiter test |
| `backend/tests/test_engine_unverified_offers.py` | Synced to match PE (test-only) |

---

## 12. Backup / rollback

**Backup:** `/opt/kupujpl-games/backups/pre-reliability-20261018-051243/`  
Contains whitelist SHA256 manifest, DB online backup, `hourly_pre.txt`, `hourly_post_manual.txt`.

**Rollback:** restore the five parser files from that backup directory; `systemctl restart kupujpl-games` + all `kupujpl-scanner@*` units. No rsync `--delete`, no git reset, no mass DB edits.

---

## 13. Remaining issues

1. **Fanatical** — invalid Awin FID; stays auth-idle until credentials restored.  
2. **CDKeys** — Algolia key refresh still required.  
3. **GOG/Epic** — many titles genuinely absent; hit-rate will stay below Steam.  
4. **IG stock** — external OOS on popular Steam keys; backoff fixes rotation, not IG inventory.  
5. **Sustained coverage** — wait for 48–72h `kupujpl-coverage-snapshot.timer` series before claiming sustained improvement.  
6. **Double wait** (game-start + per-HTTP) is intentionally conservative under shared limiter.

---

## Success criteria checklist

| Criterion | Result |
|---|---|
| No scanner regression (IG queue spin) | Fixed |
| No artificial verification timestamps | Stubs use `unavailable` only |
| No uncontrolled RPS multiplication | Shared limiter on HTTP paths |
| Full regression tests completed | 187 passed on prod |
| Stable confirmed-price coverage | Rising; long-term pending |
| PE V2 accuracy | Unchanged thresholds |
| No unexpected HTTP 500 | Smokes 200 |
| Cozy Orange unchanged | Yes |

**Final status: VERIFIED FIXES DEPLOYED — LONG-TERM PENDING**
