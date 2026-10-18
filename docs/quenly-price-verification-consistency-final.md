# Quenly — Price Verification Consistency Final Report

**Date:** 2026-10-18  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange — unchanged  
**Price Engine:** V2 — thresholds unchanged; classification hardened for miss/timeout  
**Prior:** `docs/quenly-stock-verification-stability-final.md` (`2761cc8`)  
**Status:** **VERIFIED — LONG-TERM PENDING**

Not FULLY VERIFIED: fewer than 48–72h of hourly coverage snapshots.

---

## 1. Confirmed-after-not_found verdict

**PASS — remains confirmed until normal freshness expiry.**

Scenario after stock fix + this pass:

| Field | After `not_found` on previously verified offer |
|---|---|
| `in_stock` | stays `True` |
| `last_verified_at` | unchanged |
| `last_check_status` | `not_found` |
| `price_pln` | unchanged |
| `updated_at` | **frozen** (no ORM onupdate bump) |
| PE V2 bucket | **`confirmed`** while `last_verified_at` within shop fresh window |
| Catalog `best_offers_map_v2` | still returns the offer |

Search miss is **not** treated as a successful verification and does **not** extend freshness.

After fresh window elapses → PE moves to `stale` / excluded via normal rules (tested).

Explicit `unavailable` → `in_stock=False` → not confirmed (tested).

---

## 2. PE V2 classification evidence

**Root cause found (timeout/error path):**  
`_classify_offer_row` excluded any offer whose `last_check_status` was in `_ERROR_CHECK_STATUSES` (`timeout`, `error`, `blocked`, …) **even when** `last_verified_at` was still fresh. That would drop confirmed prices after a timeout despite stock preservation.

`not_found` was **already outside** `_ERROR_CHECK_STATUSES`, so stock-only fix was sufficient for search miss — but timeout would still kill PE confirmed.

**Fix deployed:**

```text
if status in _ERROR_CHECK_STATUSES and verification_timestamp(offer) is None:
    → excluded insufficient_data
```

Prior verification timestamp present → PE continues to use freshness on `last_verified_at`.

Also: `record_attempt()` now restores prior `updated_at` so SQLAlchemy `onupdate` cannot artificially refresh freshness after a miss.

Regression tests (`tests/test_pe_confirmed_after_miss.py`):

| Test | Result |
|---|---|
| confirmed survives `not_found` + `best_offers_map_v2` | PASS |
| confirmed survives `timeout` | PASS |
| confirmed drops after freshness expiry post-`not_found` | PASS |
| explicit OOS removes confirmed | PASS |
| Tier C never-listed longer backoff | PASS |
| Tier A never-listed short backoff | PASS |

---

## 3. Legacy false OOS statistics

Read-only query: `last_verified_at` set, `price_pln > 0`, `in_stock=0`.

| Filter | Count |
|---:|---:|
| `last_check_status='not_found'` (classic false-OOS signature) | **0** |
| `last_check_status='unavailable'` | 271 |
| `last_check_status='error'` | 20 |
| Any status OOS with prior verify | 548 |

**Interpretation:** No remaining classic `not_found`+prior-verify+OOS rows (either never persisted that way long-term, or already overwritten/re-verified). The 271 `unavailable` rows may be **real** OOS; they are **not** mass-healed.

Artifact: `/opt/kupujpl-games/backend/tmp/legacy_false_oos_candidates.json` (`candidate_count=0`).

**Policy:** restore only after successful live scanner verification — no timestamp/stock mass edits.

Instant Gaming mix (context):

| Bucket | Count |
|---|---:|
| had_verify + verified + in_stock | 1517 |
| never_listed + unavailable | 883 |
| never_listed + not_found | 608 |
| had_verify + unavailable | 18 |

---

## 4. Instant Gaming efficiency analysis

Prior hour: **24 verified / 1270 attempts = 1.89%**.

**Cause:** ~1491 never-listed IG rows (`not_found`/`unavailable` without `last_verified_at`) dominate the queue. Tier C long-tail titles Instant Gaming never sold consume permitted RPS under the short 6h backoff.

**Optimization (within existing RPS):**

| Rule | TTL |
|---|---|
| Default status backoff (incl. previously verified) | `STATUS_BACKOFF_HOURS` = 6h |
| Tier C **never-listed** `not_found`/`unavailable` | `NEVER_LISTED_BACKOFF_HOURS` = **48h** (env-capped ≤72h) |
| Tier A/B never-listed (reviews ≥ `TIER_B_MIN_REVIEWS`) | stays **6h** (popular/new not buried) |

Not infinite exclusion: after 48h the title re-enters. No RPS increase.

---

## 5. Coverage metric validation (T05→T06)

| Check | Result |
|---|---|
| Snapshot times | T05 `2026-10-18T05:00:13Z`; T06 `2026-10-18T06:07:10Z` (~67 min apart) |
| Methodology | Identical note / PE V2 `best_offers_map_v2` confirmed |
| Paid denominator | **10414 = 10414** |
| Net confirmed Δ | **+2455** (3838 → 6293) |
| Tier A Δ | 0 |
| Tier B Δ | 0 |
| Tier C Δ | **+2455** |
| `stale_or_unconfirmed` Δ | **−2458** (6070 → 3612) |

**Shop attribution (verified_24h):**

| Shop | T05 v24 | T06 v24 | Δ24 |
|---|---:|---:|---:|
| **Steam** | 3897 | 6414 | **+2517** |
| Instant Gaming | 1492 | 1516 | +24 |
| Others | flat / negligible | | |

**Verdict:** The +2455 hour jump is **real PE-confirmed coverage**, almost entirely **Steam verifying Tier C** titles that move from `stale_or_unconfirmed` → `has_confirmed`. Not artificial timestamp healing. Not a counter bug. Do **not** extrapolate +2455/h as a sustained rate.

---

## 6. Full pytest results

| Suite | Result |
|---|---|
| Full local `tests/` (junit) | **229 passed, 0 failed, 0 errors** (~12.8s) |
| PE miss + stock + Playwright | **11 passed** |
| Prod `test_pe_confirmed_after_miss` + integrity | run post-deploy |

**Pytest interrupt root cause:** process receives `KeyboardInterrupt` **after** the summary line during warning/teardown flush when the parent shell times out or cancels. JUnit XML already shows a complete green suite. Mitigations used: `--junitxml`, `-p no:warnings`, `Start-Process` file redirects. Assertions not weakened.

---

## 7. Playwright results

| Test | Result |
|---|---|
| Catalog Cozy Orange | PASS |
| API price_status states | PASS |
| F2P page | PASS |
| Paid honest price | PASS |
| Rejected/unverified not mixed as confirmed | PASS |

---

## 8. Coverage before / after

| Point | Confirmed | Coverage | Tier C |
|---|---:|---:|---:|
| Task baseline (stock report) | 6293 | 60.43% | 46.65% |
| This pass (no mass DB change) | ~6293 | ~60.43% | ~46.65% |

This deploy does not invent coverage; it protects PE confirmation after misses and reduces wasted IG probes.

---

## 9. Git commits

| Commit | Topic |
|---|---|
| `2761cc8` | Stock: not_found must not OOS verified |
| *(this change)* | PE: keep confirmed through miss/timeout; freeze updated_at; Tier-C never-listed backoff; report |

Files:

- `backend/app/core/price_engine.py`
- `backend/app/core/offer_verification.py`
- `backend/app/parsers/shop_scan_queue.py`
- `backend/tests/test_pe_confirmed_after_miss.py`
- `docs/quenly-price-verification-consistency-final.md`

---

## 10. Deployed whitelist

**Backup:** `/opt/kupujpl-games/backups/pre-pe-consistency-20261018-062058`

| Path | SHA256 (new) |
|---|---|
| `price_engine.py` | `67b9d576044ad96215146e07d66c9f245b3f697486121d65b29873e70c2be14d` |
| `offer_verification.py` | `99e7f0f4c1ea5eb0f7e9e17537d1bb762273c7dcb17c401275b8211125175fc7` |
| `shop_scan_queue.py` | `2a7f8fef08741af36ed37d299ec8aa6037a19e936d31d69ca56328ced0abbadb` |

SSR/API smoke: hades `200`, api `200`. Services active.

---

## 11. Backup and rollback

```bash
BK=/opt/kupujpl-games/backups/pre-pe-consistency-20261018-062058
cp -a "$BK/backend__app__core__price_engine.py" /opt/kupujpl-games/backend/app/core/price_engine.py
cp -a "$BK/backend__app__core__offer_verification.py" /opt/kupujpl-games/backend/app/core/offer_verification.py
cp -a "$BK/backend__app__parsers__shop_scan_queue.py" /opt/kupujpl-games/backend/app/parsers/shop_scan_queue.py
systemctl restart kupujpl-games.service
for s in steam gog epic instantgaming; do systemctl restart "kupujpl-scanner@${s}.service" || true; done
```

No rsync, no DNS, no mass DB edits, no RPS increase.

---

## 12. Remaining issues

1. Need **48–72h** hourly snapshots before FULLY VERIFIED.  
2. IG efficiency still low until never-listed backoff accumulates; re-measure after ≥24h.  
3. 271 `unavailable`+prior-verify rows — manual/live re-check only, no mass heal.  
4. Steam-driven Tier C fill will slow as backlog ages — do not treat +2455/h as steady state.  
5. Full pytest parent-shell KeyboardInterrupt after green summary — use junitxml as source of truth.

---

## Final status

### **VERIFIED — LONG-TERM PENDING**

Confirmed prices survive search miss and timeout through PE V2 until freshness expires. Coverage jump T05→T06 is validated as Steam Tier C catch-up. IG queue wastes less RPS on never-listed Tier C without hiding popular titles.
