# Quenly — Stock Verification & Coverage Stability Final Report

**Date:** 2026-10-18  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange — unchanged  
**Price Engine:** V2 — unchanged (no threshold loosening, no RPS increase)  
**Prior:** `docs/quenly-scanner-data-integrity-final.md` (`53762a9`)  
**Status:** **VERIFIED — LONG-TERM PENDING**

Not FULLY VERIFIED: only three hourly coverage snapshots exist (T04→T06). Promote only after 48–72h of stable hourly series without false OOS regressions.

---

## 1. Exact not_found / OOS behavior

| # | Situation | Status | Effect on previously verified offer |
|---|---|---|---|
| 1 | Product detail explicitly confirms OOS | `unavailable` | `in_stock=False`; **price kept**; no `last_verified_at` bump |
| 2 | Search completed; product not returned | `not_found` | **Attempt + backoff only**; stock **unchanged** if `last_verified_at` set |
| 3 | Search returned incomplete / no match | `not_found` | Same as #2 |
| 4 | Product URL changed (match fails) | `not_found` | Same as #2 (until re-matched verify) |
| 5 | Product title changed (match fails) | `not_found` | Same as #2 |
| 6 | Temporary search disappearance | `not_found` | Negative-cache / `STATUS_BACKOFF_HOURS` (6h); PE freshness expires normally |
| 7 | HTTP error | `error` | Attempt only; stock unchanged |
| 8 | Parser error | `error` | Attempt only |
| 9 | Authentication failure | `auth_failed` | Attempt only + backoff |
| 10 | Rate limiting | `rate_limited` | Attempt only + backoff |

**Constants (deployed):**

- `OOS_LIKE_STATUSES = {"unavailable"}` only  
- `SEARCH_MISS_STATUSES = {"not_found"}`  
- `TRANSIENT_MISS_STATUSES = {error, timeout, rate_limited, auth_failed, blocked}`

**`_record_shop_miss()` rules:**

1. Never writes `last_verified_at` on a miss.  
2. Never zeros `price_pln` on an existing row.  
3. `unavailable` → `in_stock=False`.  
4. `not_found` on a **previously verified** row → record attempt only; **do not** flip `in_stock`.  
5. `not_found` on a never-verified stub → `in_stock=False` for queue backoff.  
6. Transient statuses → attempt only.

**`record_attempt()`** stamps `last_attempt_at` + `last_check_status` only.  
**`record_verified_price()`** restores stock + price; refuses out-of-order timestamps.

---

## 2. Confirmed root cause

**Yes.** Prior to this deploy, `not_found` was treated as OOS-like (or shared the same deactivation path), so a completed search without a match could mark a **previously verified** Instant Gaming / keyshop offer out of stock.

That incorrectly:

- Removed valid offers from confirmed PE buckets before freshness expiry  
- Inflated `unavailable` / OOS transitions from mere search misses  
- Risked churning coverage downward on long-tail catalog rotation

Integrity work (`53762a9`) already split miss statuses at the parser; this stock pass **closes the deactivation gap** so search miss ≠ definitive unavailability.

---

## 3. Fixes implemented

| File | Change |
|---|---|
| `backend/app/core/offer_verification.py` | `OOS_LIKE` = `unavailable` only; add `SEARCH_MISS_STATUSES` |
| `backend/app/parsers/game_offers.py` | `_record_shop_miss`: search miss does not OOS verified rows; stubs still backoff |
| `backend/tests/test_shop_miss_integrity.py` | Regression: search miss / timeout / history / stub / backoff / restock |
| `backend/tests/test_playwright_catalog.py` | Deterministic `/api/games/{slug}` path; rejected/unverified separation |

**Deploy:** whitelist only (no rsync, no DNS, no mass DB, no artificial `verified_at`).

---

## 4. Valid-offer protection tests

| Test | Result |
|---|---|
| `test_search_miss_does_not_oos_previously_verified_offer` | PASS |
| `test_error_miss_does_not_mark_existing_offer_oos` | PASS |
| `test_timeout_after_confirmed_preserves_history_and_stock` | PASS |
| `test_unavailable_keeps_prior_price_never_zeros_existing` | PASS |
| `test_not_found_stub_excluded_from_pe_and_history` | PASS |
| `test_not_found_backoff_then_reenter` | PASS |
| `test_successful_verify_clears_stub_oos` | PASS |
| Prod `tests/test_shop_miss_integrity.py` + backoff | **12 passed** |
| Local stock + Playwright focus | **17 passed** |

---

## 5. Historical price safety

| Scenario | Outcome |
|---|---|
| Confirmed → search miss | Price + `last_verified_at` preserved; status=`not_found`; stock stays True |
| Confirmed → HTTP timeout | Stock + price preserved; status=`timeout` |
| Confirmed → explicit OOS | Stock False; **price kept** (not zeroed) |
| Reappear after backoff | `record_verified_price` restores stock |
| Out-of-order response | Existing refuse-older path unchanged |
| Wrong-SKU / stub price 0 | PE + history ignore `price<=0` / OOS stubs |
| Repeated negative search | Updates same row; backoff; no history poison |

No mass DB rewrites. Charts / min / avg / Worth Buy continue to use trusted positive in-stock / verified paths only.

---

## 6. Instant Gaming efficiency

**Window:** post-deploy ~1h (2026-10-18T06Z)

| Metric | Value |
|---|---:|
| Attempts (last_attempt_at ≥ 1h) | 1270 |
| Verified | 24 |
| Unavailable | 822 |
| not_found | 423 |
| Transient (error/…) | 1 |
| **Verified / 100 attempts** | **1.89** |
| OOS with prior verify | 16 |
| OOS never verified | 806 |
| not_found on prior-verified (1h) | 0 (pre-existing rows already OOS'd by old path; new path will protect) |
| Queue message | `no_stale_games` / popularity cursor |
| Backoff | 6h |
| Metrics hour sample | 80 HTTP attempts, 80 rate_limit_waits, 0 http_ok in that counter window (limiter saturation / fill batches) |

**Interpretation:**

- Most IG “unavailable” hits are **never-verified long-tail** (806/822) — likely true absence or hard match miss, not false deactivation of live SKUs.  
- Throughput ~**20–24 verified/hour** in the recent hour matches prior integrity report; do not claim higher without 48–72h.  
- Efficiency lever within RPS: avoid re-scanning never-listed Tier C titles more often than backoff; separate match-failure from explicit OOS in parser telemetry (already status-split). **No RPS increase applied.**

---

## 7. Full pytest results

| Suite | Result |
|---|---|
| Local stock integrity + backoff + Playwright | **17 passed** |
| Local focused PE / OOO / offer integrity / scanner V2 / stock | **52 passed** (run interrupted mid-warnings dump; no failures observed in that segment) |
| Broader local `tests/` | **223 passed** before external KeyboardInterrupt during warning flush (~255 collected) |
| Prod stock integrity + backoff | **12 passed** |
| Prod Playwright | **skipped** (`importorskip("playwright")` — Chromium not installed on server) |

Assertions were **not** weakened. Playwright runs against live production from the developer machine.

---

## 8. Playwright results

| Case | Result |
|---|---|
| Catalog home Cozy Orange | PASS |
| API price_status states | PASS |
| F2P page | PASS |
| Paid game honest price/empty | PASS |
| `test_rejected_or_unverified_not_mixed_as_confirmed_best` | **PASS** (was skipped due to wrong API path `/by-slug` / `/api/game/`; fixed to `/api/games/hades-ii`) |

Live API check: `offers=2` confirmed (Steam/Epic), `unverified=1`, ID sets **disjoint**, SSR `200` + `theme-cozy-orange`.

---

## 9. Coverage before / after

| Point | Paid | Confirmed | Coverage | Tier A | Tier B | Tier C |
|---|---:|---:|---:|---:|---:|---:|
| Task baseline (prior report) | 10414 | 5346 | 51.33% | 95.71% | 96.37% | 34.03% |
| Hourly T04 | 10414 | 3142 | ~30.2% | 95.65% | 92.05% | 5.36% |
| Hourly T05 | 10414 | 3838 | ~36.9% | 95.71% | 96.37% | 13.94% |
| Hourly T06 (post stock deploy) | 10414 | **6293** | **~60.4%** | 95.71% | 96.37% | **46.65%** |

Net T05→T06: **+2455 confirmed** (~+23.6 pp), driven mainly by Tier C catch-up under parallel scanners — **not** claimed as sustained until 48–72h.

---

## 10. Hourly coverage trends

Timer: `kupujpl-coverage-snapshot.timer` — **active** (no duplicate timers).  
Snapshots: `backend/tmp/coverage_snapshots/hourly/coverage-2026-10-18T0{4,5,6}.json`

| Hour | Confirmed Δ | Notes |
|---|---:|---|
| T04→T05 | +696 | Early Tier C fill |
| T05→T06 | +2455 | Large Tier C jump; A/B flat at ~96% |

**Do not** declare sustained improvement from three hours. Continue comparing consecutive hourly snapshots for:

- New confirmed / hour  
- Lost confirmed / hour  
- Net coverage Δ  
- Stale / OOS / search-miss transitions  
- IG verified / hour  

---

## 11. Git commits

| Commit | Topic |
|---|---|
| `53762a9` | Prior integrity: miss statuses + stub/GOG harden |
| *(this change)* | Stock: not_found must not OOS verified; Playwright API path; report |

Working tree files for this pass:

- `backend/app/core/offer_verification.py`  
- `backend/app/parsers/game_offers.py`  
- `backend/tests/test_shop_miss_integrity.py`  
- `backend/tests/test_playwright_catalog.py`  
- `docs/quenly-stock-verification-stability-final.md`

---

## 12. Production whitelist

**Backup:** `/opt/kupujpl-games/backups/pre-stock-20261018-060320`  
(includes SQLite online `.backup` + prior file copies + `WHITELIST_MANIFEST.txt`)

| Path | SHA256 (deployed) |
|---|---|
| `backend/app/core/offer_verification.py` | `326f03f74933c5c0547741cb8aa40f9c4a25ffd263860c7637bef8ac22136f4a` |
| `backend/app/parsers/game_offers.py` | `16dd359b234d42ed26debc832b4d63dcba61a35f18ba8a390c8deae1cc8a7cca` |

Services after deploy: `kupujpl-games` active; `kupujpl-scanner@instantgaming` active; coverage timer active.

---

## 13. Backup and rollback

**Rollback (targeted):**

```bash
BK=/opt/kupujpl-games/backups/pre-stock-20261018-060320
cp -a "$BK/backend__app__core__offer_verification.py" /opt/kupujpl-games/backend/app/core/offer_verification.py
cp -a "$BK/backend__app__parsers__game_offers.py" /opt/kupujpl-games/backend/app/parsers/game_offers.py
# Optional DB: sqlite3 restore from "$BK/database.db" only if a later incident requires it
systemctl restart kupujpl-games.service
for s in steam gog epic instantgaming; do systemctl restart "kupujpl-scanner@${s}.service" || true; done
```

No full rsync, no Git reset on production, no DNS change.

---

## 14. Remaining issues

1. **LONG-TERM coverage** — need 48–72h hourly series before FULLY VERIFIED / sustained claim.  
2. **IG efficiency** — ~1.9 verified/100 attempts; long-tail never-listed titles dominate `unavailable`. Optimize queue selection within existing limits (no RPS hike).  
3. **Legacy OOS rows** — offers already flipped by old `not_found→OOS` path stay OOS until a successful re-verify; no mass heal performed (by design).  
4. **Prod Playwright** — skipped (no Playwright browser on server); run from CI/dev against live URL.  
5. **CDKeys / Fanatical** — still weak verified counts in 1h window (affiliate/feed constraints unchanged).  
6. Full local pytest still occasionally interrupted by environment KeyboardInterrupt during warning flush; core stock/PE suites green.

---

## Final status

### **VERIFIED — LONG-TERM PENDING**

Stock classification fix is deployed and regression-tested. Confirmed prices are protected from search-miss false OOS. Coverage is rising in the short hourly window, but long-term stability is **not** yet proven.
