# Quenly — Scanner Stability & Tier Classification Verification

**Date:** 2026-10-18  
**Production:** `159.195.86.11` / `https://kupujpl.pl/games/`  
**Theme:** Cozy Orange (unchanged)  
**Price Engine:** V2 — **not loosened / not changed**  
**Prior report:** `docs/quenly-scanner-bottleneck-final.md`

---

## Final status

**IMPROVED — LONG-TERM PENDING**

Tier B anomaly fixed; Steam scanner still productive after restart; confirmed coverage rose vs bottleneck baseline; hourly coverage timer already running (single timer, no duplicates).  
**Not** `SUSTAINED & VERIFIED` — fewer than 48–72 hours of hourly snapshots exist.

---

## 1. Tier B anomaly — root cause

| Finding | Evidence |
|---------|----------|
| Bug | `_classify_scan_tier` treated **membership in the full Tier-A sellers cache (5000 games)** as Tier A |
| Effect | Natural mid-band **500–4999 Steam reviews** (~1183 paid games) was almost entirely swallowed into A |
| Result | Tier B collapsed to **5** games (only mid-band titles *not* in the 5000 cache) |
| Reviews / recs / NULL | NULL/0 reviews → C (correct); recommendations were unused before |

**Not** a cosmetics problem — queue mix asked for 25% Tier B while the eligible set had almost nobody.

### Fix (honest popularity, not arbitrary %)

- Tier **A**: favorites **or** popularity ≥ 5000 reviews **or** sellers-cache **rank &lt; top 1000** (`SCAN_TIER_A_CACHE_TOP_N`, default 1000)
- Tier **B**: popularity ∈ [500, 5000)
- Tier **C**: remainder (incl. NULL/0)
- Optional: `steam_recommendations // 10` may lift popularity score (does not invent tiers)

Coverage monitor now imports the **same** `_classify_scan_tier` (no divergent copy).

---

## 2. New A/B/C distribution (production, post-deploy)

| Tier | Before (broken) | After (fixed) |
|------|-----------------|---------------|
| A | 5010 | **1726** |
| B | **5** | **1183** |
| C | 5399 | **7505** |

Paid games still **10 414**. F2P excluded **461** (unchanged).

---

## 3–4. Steam verified / unique (available window)

| Source | Value |
|--------|-------|
| Bottleneck canary (prior) | ~567 / 15 min (~2268/h est.) |
| Live cycles after stability restart | ~51–55 verified / 60 attempted / ~24s |
| Current hour metrics bucket | verified **156**, unique_games **180**, idle_sec **24**, errors **0**, http_requests **180**, batch `verified_per_hour_est` ~4500 |
| False empty queue shops (snapshot) | **[]** |
| RPS | **unchanged** (Steam 2.5) |

Wall-clock sustained rate still depends on stale backlog; treat multi-hour `verified_1h` from snapshots as truth over 48–72h.

---

## 5. Coverage before / after

| Metric | Bottleneck baseline | This verification |
|--------|---------------------|-------------------|
| Paid games | 10 414 | 10 414 |
| Paid confirmed | **2225 (21.37%)** | **3142 (30.17%)** |
| Unique confirmed delta | — | **+917** games |
| F2P excluded | 461 | 461 |
| Tier A confirmed pct | 41% of 5010 (mis-sized A) | **95.65%** of 1726 |
| Tier B confirmed pct | 40% of 5 | **92.05%** of 1183 |
| Tier C confirmed pct | ~3% | **5.36%** of 7505 |

No manual timestamp healing. No invented prices.

---

## 6. Hourly snapshots

| Item | Status |
|------|--------|
| Timer | `kupujpl-coverage-snapshot.timer` — **single** timer, hourly, `Persistent=true` |
| Path | `backend/tmp/coverage_snapshots/` + `hourly/` |
| Available history | `coverage-2026-10-18T04.json` (+ refreshed same hour after deploy) |
| Extra fields now | `host` (load/RAM), `unique_games_verified_1h`, `false_empty_queue_hint`, `baseline_ref`, shared tier classifier |
| 48–72h | **PENDING** — timer left running; do not claim sustained yet |

---

## 7–9. Tests

| Suite | Result |
|-------|--------|
| Full unit `tests/test_*.py` (excl. e2e scripts) | Green after fixes (per-file + targeted runs) |
| `PRICE_ENGINE_V2=1` regression (price_engine, F2P, upserts, contracts) | PASS |
| Tier classification regression | PASS (`test_tier_classification.py`) |
| Queue fairness | PASS |
| `store_class` on `OfferResponse` | PASS (schema field + main wiring) |
| Backend signature contracts | PASS (`test_backend_contracts.py`) |
| Live SSR bot status | PASS (200) |
| Playwright catalog (`test_playwright_catalog.py`) | PASS (1 skip when API slug variant missing) |
| e2e_prod_* scripts | Not required as pytest modules (standalone) |

---

## 10. Backend compatibility check

| Check | Result |
|-------|--------|
| Prod `compute_worth_buy` has `history_points`, `offer_verified` | OK (post prior hotfix) |
| `game_interactive_html` has `history_points` | OK |
| Deploy script **contract gate** before copy | Enforced in `deploy_stability_wl.sh` |
| Blind full-module rsync | **Not used** |
| Public `/gra/hades-ii` after deploy | **200** |

---

## 11. Git commits

| Commit | Message |
|--------|---------|
| `6064df3` | Fix empty Tier B by limiting sellers-cache Tier A to top 1000 |
| `594c753` / `f7ba7a3` | Prior bottleneck idle/cursor + report |

---

## 12. Deployed whitelist

| File | Role |
|------|------|
| `backend/app/parsers/shop_scan_queue.py` | Tier A/B/C fix + recommendations blend |
| `backend/app/core/coverage_monitor.py` | Shared classifier + host/false-empty fields |
| `backend/app/schemas/schemas.py` | `store_class` on OfferResponse |
| `backend/app/main.py` | Pass `store_class` from trust badge |

SHA256 old/new recorded in backup manifest.

---

## 13. Backup

`/opt/kupujpl-games/backups/pre-stability-verification-20261018-042830/`

- Code copies: `backend__app__*.py`
- SQLite Online Backup: `database.db` (~110 MB)
- `WHITELIST_MANIFEST.txt`

---

## 14. Rollback

1. Restore the four whitelist files from the backup dir to `/opt/kupujpl-games/...`
2. `systemctl restart kupujpl-games.service`
3. Restart `kupujpl-scanner@*.service`
4. Optional: restore `database.db` only if schema/data corruption (not expected for this pass)

---

## 15. Unresolved / residual

1. **LONG-TERM PENDING** — need 48–72h of hourly snapshots before `SUSTAINED & VERIFIED`
2. **Fanatical** still 0 (Awin FID dependency — no invented credentials)
3. **G2A** elevated `error` vs verified (403 / antibot — no bypass)
4. Tier C coverage still low (~5%) — expected; fair mix continues
5. Occasional slow Steam batch (~77s) under load — monitor, no RPS bump without proof

---

## Success criteria

| Criterion | Met? |
|-----------|------|
| Stable growth of confirmed coverage without PE loosen | **Yes** (21.37% → 30.17%) |
| Correct Tier A/B/C | **Yes** (B restored to ~1183) |
| No repeat false empty queue | **Yes** in current snapshot (`[]`) |
| No new HTTP 500 | **Yes** (hades 200; contracts) |
| Full regression without critical failures | **Yes** |
| Cozy Orange preserved | **Yes** |
