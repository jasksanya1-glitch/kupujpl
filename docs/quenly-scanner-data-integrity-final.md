# Quenly — Scanner Data Integrity & Stability Final Report

**Date:** 2026-10-18  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange — unchanged  
**Price Engine:** V2 — unchanged (no threshold loosening)  
**Prior:** `docs/quenly-scanner-reliability-final.md` (`9266f7a`)  
**Status:** **VERIFIED — LONG-TERM PENDING**

Not FULLY VERIFIED: only two hourly coverage snapshots exist (~T04→T05); 48–72h series still required.

---

## 1. Unavailable stub data-integrity verdict

**PASS (with classification fix deployed).**

| Requirement | Result |
|---|---|
| Stubs never become confirmed prices | PE skips `price_pln <= 0` and OOS |
| Stubs never become historical minimum | `record_offer_price_change` ignores `price<=0` / `in_stock=False`; rollups use trusted filters |
| Price history intact | No mass deletes; stubs do not write snapshots |
| Existing valid offers not overwritten by miss | Prior `price_pln` kept; only `in_stock` cleared for OOS-like |
| HTTP failures ≠ product unavailability | `error` / `timeout` / `rate_limited` / `blocked` do **not** force OOS on existing in-stock rows |
| No duplicate (game, shop) stubs | Second miss updates the same row |
| Backoff expires | `not_found` / `unavailable` / transient statuses in `bad` set |
| Restock → verified | `record_verified_price` restores `in_stock` + price |
| Out-of-order | Existing `record_verified_price` refusal unchanged |

---

## 2. OOS / search-miss classification

| Status | Meaning | Marks OOS? |
|---|---|---|
| `unavailable` | Title matched; listings explicitly out of stock (`has_stock=0`) | Yes |
| `not_found` | Search completed; no matching product | Yes (no sellable offer) |
| `error` | Transport / unexpected failure | No (existing stock preserved) |
| `timeout` | Timeout | No |
| `rate_limited` | HTTP 429 | No |
| `blocked` / `auth_failed` | HTTP 403/401 / auth | No |
| `verified` | Live success | N/A |

Instant Gaming parser now returns a 4th miss-status element. Generic deactivate default is `not_found`, not blanket `unavailable`.

---

## 3. Instant Gaming recovery measurements

| Window | IG verified/h | Notes |
|---|---:|---|
| Pre-fix spin era (15m canaries) | ~0 | Popular OOS loop |
| Reliability hour (earlier) | 15–60 | After stub backoff |
| Integrity post (`05:44Z`) | **20** | Mid-catalog titles (Styx, Transport Fever, Melvor Idle, …) — **not** Hades/Stardew loop |

Queue still shows occasional `last_batch_verified=0` batches (expected when a batch is all misses under backoff fill), but **successful verifications continue** across the hour and titles rotate.

`ig_status` includes `not_found=33`, `unavailable=715`, `verified=1520`.

Do **not** treat a single batch of 3 verifies as sustained proof; use hourly counters above.

---

## 4. GOG remaster matching verification

- Remaster strip remains for official current SKU (Witcher 3 Remastered).
- Added `_gog_edition_forbidden`: deluxe / GOTY / complete / definitive / gold / bundle rejected unless query asks.
- DLC `productType` rejected.
- Tests: remaster accepted; complete/Witcher 2/DLC rejected.

---

## 5. Price-history regression results

Integrity tests cover stub exclusion from PE + `lowest_ever` rollups.  
Worth Buy / history paths already require `price_pln > 0` and in-stock / trusted snapshots — stubs cannot poison charts or Buy Now.

Worth Buy signature gate (`history_points`) checked at deploy.

---

## 6. Full pytest

**Production venv:** `194 passed` (`PRICE_ENGINE_V2=1`, live HTTP skipped for suite speed; e2e cozy ignored).

Local integrity + PE + worth-buy subset: **44 passed** before deploy.

---

## 7. Playwright results

Environment had a working Chromium:

| Result | Count |
|---|---|
| Passed | **4** |
| Skipped | 1 (`test_rejected_or_unverified_not_mixed_as_confirmed_best`) |

**Not BLOCKED.** Cozy Orange theme asserted on catalog home.

---

## 8. Live API / SSR checks

| Check | Result |
|---|---|
| `/games/gra/hades-ii` | 200 |
| `/games/gra/cyberpunk-2077` | 200 |
| Playwright catalog API `?limit=12` | 200 |
| Controlled IG/GOG probes | Within existing scanner budgets only |

---

## 9. Confirmed coverage before / after

| Moment | Confirmed | % | Tier C % |
|---|---:|---:|---:|
| Reliability baseline (report) | 4464 | 42.87 | 22.28 |
| Hourly snap T04 | 3142 | 30.17 | 5.36 |
| Hourly snap T05 | 3838 | 36.85 | 13.94 |
| Live post-integrity `05:44Z` | **5346** | **51.33** | **34.03** |

Gross newly confirmed ≫ net hourly snap lag (snap file trails live DB). Net coverage is rising; long-term still PENDING.

Tier A/B remain ~95.7% / ~96.4%.

---

## 10. Hourly scanner throughput (1h, post)

| Shop | verified/h |
|---|---:|
| Steam | 2220 |
| GOG | 35 |
| Epic Games | 38 |
| Instant Gaming | 20 |

RPS unchanged.

---

## 11. Git commit hashes

- Prior reliability: `9266f7a`  
- This integrity pass: (see `git log` after commit) miss classification + GOG edition guards + tests  

---

## 12. Deployed whitelist

| File | Role |
|---|---|
| `backend/app/core/offer_verification.py` | `not_found`, OOS vs transient sets |
| `backend/app/parsers/game_offers.py` | `_record_shop_miss` + fetch miss map |
| `backend/app/parsers/instant_gaming_parser.py` | OOS vs not_found vs HTTP statuses |
| `backend/app/parsers/shop_scan_queue.py` | backoff includes `not_found` |
| `backend/app/parsers/gog_parser.py` | edition safety with remaster strip |
| `backend/tests/test_shop_miss_integrity.py` | New regression suite |

---

## 13. Backup

`/opt/kupujpl-games/backups/pre-integrity-20261018-053951/`  
SHA256 manifest + SQLite online backup + prior file copies.

---

## 14. Rollback

Restore the five whitelist files from that backup; restart `kupujpl-games` + `kupujpl-scanner@*`.  
No rsync `--delete`, no git reset, no mass DB cleanup.

---

## 15. Remaining issues

1. Fanatical Awin FID still invalid.  
2. CDKeys Algolia auth still flaky.  
3. IG external stock gaps remain (backoff rotates; cannot invent stock).  
4. Only **2** hourly coverage files so far — need 48–72h before SUSTAINED / FULLY VERIFIED.  
5. One Playwright case still skipped (unverified/rejected mix sample).  
6. Occasional IG batch `verified=0` under miss-heavy windows — monitor hourly, not per-batch.

---

## Final status

**VERIFIED — LONG-TERM PENDING**

Data-integrity fixes verified by tests + production deploy; Playwright catalog E2E ran (4 passed); coverage rising. Full long-term sustainability not yet proven.
