# Quenly — 72h Price Coverage Stability Observation

**Date:** 2026-10-18  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange — unchanged  
**Price Engine:** V2 — thresholds unchanged  
**Prior:** `docs/quenly-price-verification-consistency-final.md` (`4e7cf42`)  
**Status:** **STABLE — OBSERVATION PENDING**

**Not** `SUSTAINED & VERIFIED`: only **~1.5 hours** of consecutive hourly snapshots exist (3 files). Need **48–72h** of real observations. Timer is active; no future snapshots were manufactured.

**Deploy:** none this pass (no confirmed production defect requiring a fix).

---

## 1. Available hourly snapshots

Timer: `kupujpl-coverage-snapshot.timer` — **active**  
Last: `2026-10-18 08:00:31 CEST` → `coverage-2026-10-18T06.json`  
Next: `2026-10-18 09:00:01 CEST`

| File | generated_at (UTC) | Paid | Confirmed | Coverage % | Tier A % | Tier B % | Tier C % |
|---|---|---:|---:|---:|---:|---:|---:|
| `coverage-2026-10-18T04.json` | 04:37:09 | 10414 | 3142 | 30.17 | 95.65 | 92.05 | 5.36 |
| `coverage-2026-10-18T05.json` | 05:00:13 | 10414 | 3838 | 36.85 | 95.71 | 96.37 | 13.94 |
| `coverage-2026-10-18T06.json` | 06:07:10 | 10414 | 6293 | 60.43 | 95.71 | 96.37 | 46.65 |

**Live read (same PE V2 method, not yet flushed to hourly file):** confirmed **7127** / **68.44%** (Tier C **57.75%**). Awaiting T07+ hourly files for trend continuity.

Observation span (first→last snapshot): **~1.5 h**.  
`sufficient_for_sustained_claim`: **false**.

---

## 2. Confirmed coverage trend

```
T04  30.17% ████
T05  36.85% █████
T06  60.43% █████████
live 68.44% ██████████  (pre-T07)
```

Paid denominator constant **10414**. Methodology identical (`build_coverage_snapshot` / PE V2 `best_offers_map_v2`).

Rapid rise is **Steam Tier C catch-up**, not counter inflation. Do not treat the slope as a steady-state rate.

---

## 3. Tier A/B/C trends

| Window | Tier A confirmed | Tier B | Tier C |
|---|---:|---:|---:|
| T04 | 1651 (95.65%) | 1089 (92.05%) | 402 (5.36%) |
| T05 | 1652 (95.71%) | 1140 (96.37%) | 1046 (13.94%) |
| T06 | 1652 (95.71%) | 1140 (96.37%) | 3501 (46.65%) |
| Live | 1652 (95.71%) | 1141 (96.45%) | 4334 (57.75%) |

A/B saturated and stable. C still climbing while Steam backlog clears.

---

## 4. Newly confirmed vs expired

Consecutive snapshot deltas (identical classification):

| From→To | Net confirmed | Tier C Δ | stale_or_unconfirmed Δ | Steam v24 Δ |
|---|---:|---:|---:|---:|
| T04→T05 | +696 | +644 | −696 | +820 |
| T05→T06 | +2455 | +2455 | −2458 | +2517 |

Live vs T06: **+834** confirmed (7127−6293), stale pool still shrinking (2778 left).

**Gross gain vs loss:** hourly files do not store per-game gain/loss sets; net = confirmed Δ. Proxy: `stale_or_unconfirmed` decline ≈ conversion into confirmed (not mass expiry). No evidence that confirmed prices expire faster than revalidation **in this short window** — Steam v24 growth dominates. Re-evaluate after 48–72h when freshness churn becomes visible.

Artifact: `/opt/kupujpl-games/backend/tmp/stability_observe.json`

---

## 5. Scanner verified/hour

From T06 shop rows + live IG 1h window:

| Shop | verified_1h (T06 snap) | Notes |
|---|---:|---|
| Steam | ~2260 | Primary coverage driver |
| Instant Gaming | 24 (snap) / **13** (live 1h) | Low yield |
| Keyshops / GOG / Epic | ~30–40 each | Steady |

---

## 6. Instant Gaming 48h backoff

Config on prod: `STATUS_BACKOFF_HOURS=6`, `NEVER_LISTED_BACKOFF_HOURS=48`.

| Metric | Pre-consistency (~T06) | This observation (~08:30 CEST) |
|---|---:|---:|
| Attempts/h | 1270 | 1307 |
| Verified/h | 24 | 13 |
| Verified / 100 attempts | 1.89 | **0.99** |
| not_found | 423 | **900** |
| unavailable | 822 | 393 |

Queue: `phase=running`, message=`no_stale_games`.

**Read:** 48h backoff only helps **after** the first miss. First-contact Tier C probes still burn RPS (`not_found` ↑). Popular/new titles keep **6h** backoff (Tier A/B). Too early to judge efficiency improvement — need ≥24–48h post-deploy. **No RPS increase.** No artificial timestamp healing.

---

## 7. Legacy unavailable sample

Total: **273** offers with prior `last_verified_at`, `in_stock=0`, `last_check_status=unavailable`, `price_pln>0`.  
Classic false-OOS (`not_found` + prior verify + OOS): **0**.

Read-only popular sample (no mass restore):

| Title (slug) | Shop | Reviews | Price | Last verified | Last attempt |
|---|---|---:|---:|---|---|
| detroit-become-human | Instant Gaming | 250k | 24.45 | 2026-10-16 | 2026-10-18 (unavailable) |
| payday-3 | Instant Gaming | 65k | 56.82 | 2026-10-16 | 2026-10-18 |
| forager | Instant Gaming | 44k | 23.12 | 2026-10-15 | 2026-10-18 |
| car-mechanic-simulator-2021 | CDKeys | 37k | 20.49 | 2026-10-17 | 2026-10-18 |
| dmc-devil-may-cry | Instant Gaming | 33k | 17.45 | 2026-10-16 | 2026-10-18 |
| … | … | … | … | … | … |

**Classification (sample):** prior successful verify, later **explicit unavailable** status — consistent with **real OOS / listing gone**, not the old search-miss false path. CDKeys rows may also reflect auth/source limits. **No live mass re-check performed; no stock restored** without evidence.

---

## 8. Verification timestamp safety

| Mechanism | Verdict |
|---|---|
| `verification_timestamp()` | Prefers `last_verified_at`; legacy `updated_at` only if status ∈ {None,"","verified"} |
| Failed status + no `last_verified_at` | timestamp **None** → cannot fake confirmation |
| `record_attempt()` | Does not set `last_verified_at`; **freezes `updated_at`** |
| `record_verified_price()` | Sets verified stamps; refuses out-of-order |
| `_classify_offer_row` | Infra errors exclude only when no prior verification timestamp; match/URL/SKU gates still apply |

Regression tests added/kept (`tests/test_pe_confirmed_after_miss.py`):

- Confirmed survives not_found / timeout / auth_failed  
- Expires after freshness window  
- Explicit OOS drops confirmed  
- Legacy `updated_at` ignored after failed status  
- Legacy unset status may use `updated_at`  
- Wrong SKU not confirmed despite fresh stamps  

---

## 9. Price parity results

Read-only SSR ↔ API for representative slugs (Cozy Orange SSR, disjoint unverified):

| Game | API best | SSR answer | Match | Unverified separated |
|---|---|---|---|---|
| Rogue Trader | Steam 14.99 confirmed | 14.99 | ✓ | ✓ (3 unverified) |
| Hades II | Steam 117.00 | 117.00 | ✓ | ✓ |
| Satisfactory | Gamivo 93.71 | 93.71 | ✓ | ✓ |
| ULTRAKILL | Kinguin 30.96 | 30.96 | ✓ | ✓ |
| Guacamelee | Kinguin 4.80 | 4.80 | ✓ | ✓ |
| Cyberpunk 2077 | GOG 59.69 | 59.69 | ✓ | ✓ (0 unverified) |

Search hit when returned matched confirmed price (Hades II, Cyberpunk). Historical lows present and non-zero. No artificial freshness observed on these pages.

---

## 10. Full pytest results

| Suite | Result |
|---|---|
| Full `tests/` (junit) | **233 passed, 0 failed, 0 errors** |
| Focused PE/stock/Playwright/integrity | **58 passed** |
| `PRICE_ENGINE_V2=1` | enabled for runs |

Parent-shell `KeyboardInterrupt` may still appear **after** the green summary; junit XML is the source of truth.

---

## 11. Playwright results

| Test | Result |
|---|---|
| Catalog Cozy Orange | PASS |
| API price_status | PASS |
| F2P | PASS |
| Paid honest price | PASS |
| Rejected/unverified not mixed | PASS |

---

## 12. Production status

| Check | Result |
|---|---|
| `kupujpl-games` | active |
| `kupujpl-coverage-snapshot.timer` | active |
| `kupujpl-scanner@steam` / `@instantgaming` | active |
| Home / Hades SSR | HTTP 200 |
| PE V2 / Cozy Orange | unchanged |
| RPS | unchanged |

---

## 13. Git commits

| Commit | Topic |
|---|---|
| `4e7cf42` | Prior PE consistency (miss/timeout / never-listed backoff) |
| `5854645` | Timestamp integrity regression tests + this 72h observation report |

No production whitelist deploy this pass.

---

## 14. Deployment details

**None.** No confirmed defect requiring code/config change on the server.

---

## 15. Remaining issues

1. **Observation window too short** (~1.5h snapshots; live already ahead of T06) — continue timer through **48–72h**.  
2. **IG efficiency** still ~1% verified/attempt; 48h backoff needs longer soak; first-contact Tier C still expensive.  
3. **273 legacy unavailable** — treat as likely real OOS unless live evidence says otherwise; no mass heal.  
4. Re-measure **confirmed expiry vs revalidate** after freshness windows elapse on the newly confirmed Tier C cohort.  
5. Do not claim sustained coverage growth from Steam backlog catch-up alone.

---

## Final status

### **STABLE — OBSERVATION PENDING**

Production is healthy, PE/timestamp guards hold under tests, price parity on sample games is consistent, and the hourly coverage timer is writing. Long-term sustainability is **not yet proven** — keep collecting consecutive hourly snapshots for 48–72 hours before any `SUSTAINED & VERIFIED` claim.
