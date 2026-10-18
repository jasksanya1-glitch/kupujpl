# Quenly — Catalog Price Coverage Audit & Fix

**Date:** 2026-10-18  
**Production:** `159.195.86.11` / `https://kupujpl.pl/games/`  
**Theme:** Cozy Orange  
**Price Engine:** V2 (`PRICE_ENGINE_V2=1`)  
**Verdict:** **IMPROVED — STALE THROUGHPUT REMAINS PRIMARY GAP**

Accuracy of confirmed prices was prioritized over fill rate. PE V2 rules were **not** loosened globally.

---

## 1. Catalog totals (mutually exclusive)

Full read-only pass over production DB (`tmp/catalog_coverage_audit.py`).

| Metric | Before | After |
|--------|--------|-------|
| Total games | **10 875** | **10 875** |
| With confirmed PE V2 price | **1 019 (9.37%)** | **1 125 (10.34%)** |
| Without confirmed price | 9 856 | 9 750 |
| Delta confirmed | — | **+106 games** |

### Mutually exclusive states

| State | Before | After | Meaning |
|-------|--------|-------|---------|
| `has_confirmed` | 1 019 | 1 125 | ≥1 offer passes PE V2 confirmed |
| `stale_only` | 8 791 | 8 684 | Match-eligible offers exist but fail freshness |
| `offers_oos_or_zero` | 922 | 923 | Offer rows exist; none in-stock with price > 0 for PL |
| `rejected_only` | 118 | 118 | All visible candidates PE-rejected |
| `unverified_only` | 16 | 16 | Only unverified / low-confidence rows |
| `no_offers` | 9 | 9 | Zero Offer rows |
| `never_scanned` (exclusive) | 0 | 0 | Folded into `no_offers` (all 9 have catalog rows but no offers) |
| `scanner_failed` (exclusive) | 0 | 0 | Failures appear as offer `last_check_status` / PE reasons, not a separate game bucket |

**Games with Offer rows but no confirmed price in UI:** `without_confirmed − no_offers` = **9 741** (after).

**Confirmed coverage:** **10.34%** of catalog (was 9.37%).

---

## 2. Root-cause taxonomy (not “Brak ofert”)

### Primary (catalog-wide)

1. **Stale verification / scanner throughput (~80% of catalog)**  
   Offers exist and often match, but `last_verified_at` / freshness window (24h keyshops, 36h Steam/GOG/Epic) is exceeded. systemd units are `active` while **verified_last_24h ≪ in_stock**.  
   Bug: same-price upsert did **not** stamp `last_verified_at` → once set, PE ignored newer `updated_at`. **Fixed in code.**

2. **OOS / free-to-play / zero-price (~8.5%)**  
   Popular F2P (CS2, Dota, Apex, Warframe, …) have rows but no sellable base SKU for PL.

3. **PE rejections (correct, keep strict)**  
   Offer-level reasons (after): `stale` 14 806, `price_anomaly` 4 037, `edition_mismatch` 2 212, `insufficient_data` 1 132, `match_mismatch` 113, `low_confidence` 107, `not_eligible` 34.

4. **Unverified-only (16)** — left unverified; no fake confirm.

5. **No offers (9)** — DLC/orphans/bad titles; auto-fixable via scan queue, not invented prices.

### Path check: Game → Scanner → Raw Offer → Matching → DB → PE V2 → API → Frontend

| Layer | Finding |
|-------|---------|
| Scanner | Units active; Instant Gaming & CDKeys strong 24h verify; Steam/G2A/Fanatical weak vs stock |
| Matching | Edition/anomaly rejections intentional |
| PE V2 | Confirmed-only for catalog `best_price_pln` — correct; not loosened |
| API | `price_status`: `confirmed` \| `no_confirmed` \| `no_offers` |
| Frontend | Cozy Orange labels: confirmed price / «Brak potwierdzonej ceny» / «Brak aktualnych ofert» |

---

## 3. Breakdown by shop / category / popularity

### Confirmed best-offer by shop (after)

| Shop | Games with confirmed best |
|------|---------------------------|
| Instant Gaming | 540 |
| Steam | 229 (+105 vs 124 before; targeted Steam refresh) |
| GOG | 155 |
| Epic Games | 85 |
| Kinguin | 74 |
| Gamivo | 39 |
| G2A | 3 |

### Category coverage (after, top)

| Category | Games | Confirmed | % |
|----------|-------|-----------|---|
| feat-jednoosobowa | 3239 | 295 | 9.1 |
| feat-udostepnianie-gier | 2827 | 267 | 9.4 |
| feat-osiagniecia-steam | 2245 | 330 | 14.7 |
| niezalezne | 1963 | 156 | 7.9 |
| akcja | 1570 | 163 | 10.4 |
| feat-steam-cloud | 1298 | 155 | 11.9 |
| przygodowe | 1144 | 122 | 10.7 |
| rpg | 1014 | 90 | 8.9 |
| feat-karty-kolekcjonerskie-steam | 933 | 161 | 17.3 |
| feat-zawartosc-do-pobrania | 781 | 14 | 1.8 |

Popularity proxy = `steam_review_count + steam_recommendations`. Stale gap dominates even high-review titles until re-verified within the fresh window.

---

## 4. Scanner effectiveness (not systemd alone)

Snapshot `2026-10-18T03:17:59Z` (`tmp/scanner_eff.json`). All listed units **active**.

| Shop | In-stock priced | Verified 24h | Success share 24h | Updated 72h | Last verified | Notes |
|------|-----------------|--------------|-------------------|-------------|---------------|-------|
| Steam | 9 651 | 147 | 1.5% | 3 638 | 2026-10-18 | Throughput << catalog; priority queue helps |
| GOG | 1 585 | 85 | 5.4% | 1 333 | 2026-10-18 | OK official |
| Epic Games | 1 809 | 88 | 4.9% | 1 515 | 2026-10-18 | OK official |
| Instant Gaming | 1 538 | 1 221 | **79.4%** | 1 453 | 2026-10-18 | Best keyshop coverage |
| Kinguin | 3 528 | 195 | 5.5% | 1 057 | 2026-10-18 | Large stock, slow verify |
| G2A | 4 043 | 30 | 0.7% | 145 | 2026-10-18 | Errors present; weak refresh |
| Gamivo | 2 069 | 108 | 5.2% | 847 | 2026-10-18 | Moderate |
| CDKeys | 1 391 | 640 | **46.0%** | 1 259 | 2026-10-17 | Strong when Algolia key valid |
| Fanatical | 320 | 0 | 0% | 1 398 | null | Updates without `verified` stamp |

Anti-bot / rate-limit: soft-fail design in `shop_scan_queue` (no CAPTCHA bypass). G2A/Fanatical show effective under-verification, not “inactive systemd”.

Regularly skipped: long-tail games (starvation every Nth pick); F2P/OOS; Fanatical never sets `last_check_status=verified`.

---

## 5. Price Engine V2

Checked: freshness, Steam reference anomaly, keyshop floor, URL, edition, confidence, region/DRM.

- **No global loosening.**
- False-reject root cause for many “valid but invisible” prices was **stale stamp**, not over-strict anomaly floors.
- Regression: `tests/test_upsert_stamps_verification.py` (same-price upsert bumps `last_verified_at`).

---

## 6. Catalog UI (Cozy Orange)

| State | Display |
|-------|---------|
| Confirmed | Lowest confirmed price |
| Offers but no confirmed | «Brak potwierdzonej ceny» (`price_status=no_confirmed`) |
| No offers | «Brak aktualnych ofert» |
| Scanning | Unchanged — only if real scan in progress |

No fake prices; no hiding games; no Cozy redesign. Cache bust: `app.js?v=98`, `i18n.js?v=29`.

---

## 7. Fixes applied

### Code (whitelist deploy)

| File | Change |
|------|--------|
| `parsers/keyshop_common.py` | Always `record_verified_price` on upsert (incl. same price) |
| `parsers/steam_catalog.py` | Same for Steam upsert |
| `core/product_matching.py` | Freshness via `verification_timestamp` |
| `parsers/shop_scan_queue.py` | Prefer popular / Tier A + fair oldest mix |
| `main.py` + `schemas.py` | `price_status` on catalog list |
| `static/app.js` + `i18n.js` | Empty-price labels PL/UK/EN |
| `index.html` / `seo_pages.py` | Cache-bust static versions |

### Production DB (limited, permitted-safe)

1. **Verification heal:** 28 offers with `last_verified_at < updated_at` within freshness → stamp aligned (dry-run first).  
2. **Targeted Steam refresh:** top 40 popular missing confirmed, Steam-only, 1.5s spacing → **36/40 gained confirmed** (4 remain: GTA V Legacy edition/SKU, Friend's Pass, FC 24/25 keyshop-only stale).

**No mass catalog rescan. No PE floor changes.**

### Backup / rollback

- Backup: `/opt/kupujpl-games/backups/pre-coverage-audit-20261018-031130/` (10 files)  
- Rollback: copy from that dir over live paths; `systemctl restart kupujpl-games.service` (+ scanner units if needed)

---

## 8. Sample: 100 games without confirmed price

Balanced across `stale_only`, `offers_oos_or_zero`, `rejected_only`, `unverified_only`, `no_offers` (after snapshot). Full JSON: `tmp/catalog_coverage_after.json` → `sample_100`.

| # | Title | Game ID | Steam | Offers | Shops | Last update | Raw min | Reason | Auto-fix |
|---|-------|---------|-------|--------|-------|-------------|---------|--------|-----------|
| 1 | Grand Theft Auto V Legacy | 3 | 271590 | 11 | - | 2026-10-18T03:13 | 44.09 | offers_oos_or_zero | yes |
| 2 | GOALS | 361 | 2753000 | 4 | - | 2026-10-14T21:08 | 36.99 | offers_oos_or_zero | yes |
| 3 | Eterspire | 203 | 2144600 | 1 | - | 2026-10-16T14:37 | - | offers_oos_or_zero | yes |
| 4 | Modern Warships | 413 | 3144230 | 4 | - | 2026-10-14T21:08 | 3.24 | offers_oos_or_zero | yes |
| 5 | Farm RPG | 712 | 2287550 | 5 | - | 2026-10-14T21:08 | 7.67 | offers_oos_or_zero | yes |
| 6 | Soul Land: Awakening World | 1082 | 4584110 | 4 | - | 2026-10-14T21:08 | 54.71 | offers_oos_or_zero | yes |
| 7 | Gunk | 752 | 4732810 | 10 | - | 2026-10-14T21:10 | 5.27 | offers_oos_or_zero | yes |
| 8 | Phoenix 2 | 1026 | 2678070 | 5 | - | 2026-10-14T21:08 | 5.76 | offers_oos_or_zero | yes |
| 9 | Goalkeeper Journey | 148 | 3239960 | 7 | - | 2026-10-14T21:10 | 5.33 | offers_oos_or_zero | yes |
| 10 | 坍塌世界 | 832 | 4501210 | 1 | - | 2026-06-17T08:29 | - | offers_oos_or_zero | yes |
| 11 | Classic: Snake | 129 | 4742330 | 8 | - | 2026-10-14T21:08 | 4.0 | offers_oos_or_zero | yes |
| 12 | Dustin Sunset | 34 | 4182710 | 5 | - | 2026-10-14T21:08 | 14.93 | offers_oos_or_zero | yes |
| 13 | Cyberpunk 2077: Widmo wolności | 16 | 2138330 | 8 | Epic, G2A, Gamivo, Steam | 2026-10-17T00:42 | 59.69 | stale_only | yes |
| 14 | METAL SLUG 3 | 20 | 250180 | 10 | multi | 2026-10-17T20:15 | 2.16 | stale_only | yes |
| 15–24 | (stale long-tail / CN titles) | — | — | — | — | — | — | stale_only | yes |
| 25–36 | Cry of Fear, HITMAN, AoE III, … | — | — | — | — | — | — | rejected_only | no |
| 37–48 | ATS Arizona, Fall Guys, … | — | — | — | — | — | — | unverified_only | no |
| 49–57 | DLC / orphans / bad URL title | — | — | 0 | - | - | - | no_offers | yes |
| 58–83 | CS2, PUBG, Dota, Apex, … F2P | — | — | — | - | — | — | offers_oos_or_zero | yes |
| 84–85 | EA FC 24 / 25 | 1644 / 1710 | — | — | keyshops | — | 28.75 | stale_only | yes |
| 86–100 | Delta Force, TW3K, TEKKEN 7, … | — | — | — | — | — | — | stale / oos | mixed |

Complete 100-row table with shops/raw prices: see `tmp/sample100_md.txt` and `tmp/catalog_coverage_after.json`.

---

## 9. Tests

| Suite | Result |
|-------|--------|
| `tests/test_upsert_stamps_verification.py` | **2 passed** |
| Price-related (`test_price_engine`, `test_engine_unverified_offers`, `test_offer_integrity`, `test_price_parity_sample`, `test_promocje_price_parity_v2`, `test_scanner_reliability_v2`) + upsert | **45 passed** (`PRICE_ENGINE_V2=1`) |
| Full `pytest tests/` | Blocked by pre-existing `test_polish_dubbing_model.py` ImportError (unrelated) |
| Playwright | Not re-run this pass (UI change is label + `price_status` only; API smoke confirmed) |
| API smoke | `price_status` present on `/api/games`; confirmed vs `no_confirmed` correct |

---

## 10. Git commits

Branch: `fix/quenly-production-stabilization-20261017`

| Commit | Message |
|--------|---------|
| `d63106e` | Fix catalog confirmed-price coverage without loosening PE V2. |

Includes: verification stamp on upsert, popular scan queue, catalog `price_status` + Cozy Orange empty labels, upsert regression test, this report.

---

## 11. Production files changed (whitelist)

```
/opt/kupujpl-games/backend/app/parsers/keyshop_common.py
/opt/kupujpl-games/backend/app/parsers/steam_catalog.py
/opt/kupujpl-games/backend/app/parsers/shop_scan_queue.py
/opt/kupujpl-games/backend/app/core/product_matching.py
/opt/kupujpl-games/backend/app/main.py
/opt/kupujpl-games/backend/app/schemas/schemas.py
/opt/kupujpl-games/backend/app/static/app.js
/opt/kupujpl-games/backend/app/static/i18n.js
/opt/kupujpl-games/backend/app/static/index.html
/opt/kupujpl-games/backend/app/core/seo_pages.py
```

---

## 12. Backup & rollback

| Item | Path |
|------|------|
| Backup | `/opt/kupujpl-games/backups/pre-coverage-audit-20261018-031130/` |
| Deploy script | `/tmp/quenly-coverage-wl/deploy_coverage_wl.sh` |
| Service | `kupujpl-games.service` → **active** after deploy |

Rollback: restore the 10 backed-up files → restart `kupujpl-games` (+ scanners).

---

## 13. Remaining issues

1. **~8 684 games still `stale_only`** — needs sustained scanner throughput (popularity-first queue deployed; do **not** raise global RPS without load review).  
2. **F2P / OOS (~923)** — correctly no confirmed base price.  
3. **Rejected / unverified (~134)** — keep PE strict; fix matching case-by-case.  
4. **Fanatical** never stamps verification.  
5. **G2A** near-zero 24h verify rate.  
6. **GTA V Legacy / Friend's Pass / some sports titles** — edition or missing Steam PL SKU after forced refresh.  
7. Full pytest blocked by unrelated polish-dubbing import.

---

## Artifacts

| Artifact | Location |
|----------|----------|
| Before stats | `tmp/catalog_coverage_out.json` |
| After stats | `tmp/catalog_coverage_after.json` |
| Sample 100 MD | `tmp/sample100_md.txt` |
| Scanner effectiveness | `tmp/scanner_eff.json` |
| Audit script | `tmp/catalog_coverage_audit.py` |
| Deploy | `tmp/deploy_coverage_wl.sh` |

---

**Bottom line:** Confirmed catalog coverage **9.37% → 10.34% (+106)** with accurate PE V2 prices. Dominant remaining gap is **scanner freshness throughput**, not missing Offer rows and not over-strict anomaly rules. Further gains should come from controlled popular-first re-verification, not invented offers or loosened confirmation thresholds.
