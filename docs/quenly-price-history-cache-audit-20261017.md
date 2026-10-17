# Quenly — Price Accuracy & Historical Data Audit (2026-10-17)

**Status: STABLE WITH ISSUES**

Matching, confirmed-best parity, and display separation were verified for the four focus games and a full production DB skim. Trusted historical lows are computed on read (PE V2) without mass DB rewrite. Catalog cards may still show stored `lowest_ever_pln` until an approved rollup refresh. Playwright E2E and full green pytest were not completed in this pass (known unrelated collection error + intermittent suite interrupt).

---

## A. Price Engine

### Scale (production DB, read-only, PRICE_ENGINE_V2=1)

| Metric | Count |
|--------|------:|
| Games (non-free, with slug) | 8227 |
| Visible in-stock offers (PL) | 20072 |
| Confirmed offer rows | 2049 |
| Stale offer rows | 10869 |
| Excluded offer rows | 5604 |
| Unverified (display helper) | 3536 |
| Games with cheaper non-confirmed than confirmed | 1008 |
| Suspected wrong-SKU (`match_mismatch` / `edition_mismatch`) | 1862 |
| Suspicious stored historical lows (vs Steam × 0.22) | 616 |
| Invalid affiliate URLs | 0 |
| In-stock offers not updated ≥14d | 9580 |
| Games with no visible offers | 51 |

**Top exclusion reasons:** stale (10869), price_anomaly (2973), edition_mismatch (1759), insufficient_data (636), match_mismatch (103), low_confidence (100).

### Focus games (production PE dump)

#### Satisfactory (`satisfactory-526870`)
- **Confirmed best:** Instant Gaming **97.94 PLN** (fresh).
- **Cheaper Gamivo 93.25:** bucket `stale` — identity OK, freshness fails → not confirmed.
- **Stored `lowest_ever_pln`:** 93.25 (contaminated by stale Gamivo).
- After deploy: Gamivo moves to **Oferty niezweryfikowane** with user-facing stale reason; hero shows **Najniższa potwierdzona**.

#### ULTRAKILL (`ultrakill-1229490`)
- **Confirmed best:** Instant Gaming **33.20 PLN**.
- **Cheaper Gamivo 21.43:** `price_anomaly` (unverified, not confirmed). Threshold not loosened.
- **Kinguin** was previously stale / not confirmed best (trust floor intact).
- **Stored lowest:** 21.43 (anomaly pollution).

#### Guacamelee! STCE (`guacamelee-super-turbo-championship-edition-275390`)
- **Confirmed best:** Kinguin **4.80 PLN**.
- **Historical 2.29 (Gamivo):** `insufficient_data` — not confirmed; fails PE history steam-ratio floor (2.29 / Steam ≈ 0.14 < 0.22).
- **Stored lowest:** 2.29 → discarded on trusted compute; UI shows confirmed historical band.

#### Rogue Trader (`warhammer-40000-rogue-trader-2186680`)
- **Confirmed best:** Epic Games **199.99 PLN**.
- **GOG 8.99:** `edition_mismatch` → **rejected** (not buyable, not unverified list).
- **Kinguin 33.46:** `price_anomaly` → unverified only.
- **Stored lowest:** 199.99 (OK). Rejected GOG does not drive discount / recommendation / history.

### Code fixes (this pass)
1. Main offer table = **confirmed only** (stale fallback only when no confirmed).
2. Stale + plausible excluded → **unverified** with plain-language reason.
3. History rollups / charts use PE confirmed peers + **KEYSHOP_CONFIRMED_STEAM_RATIO (0.22)** under V2.
4. `trusted_history_display` for game API / SSR / Worth Buy (no mass DB delete).
5. Label **Najniższa potwierdzona** when `price_confirmed`.
6. SEO price landings: `Cache-Control: no-cache, must-revalidate`.

---

## B. Historical Prices

| Item | Value |
|------|------:|
| Suspicious stored lows (steam-ratio skim) | 616 |
| Confirmed pollution examples | Guacamelee 2.29; ULTRAKILL 21.43; Satisfactory 93.25 |
| Mass DB cleanup | **Not executed** (dry-run only; needs approval) |
| Display/Worth Buy | Uses trusted compute under PE V2 |
| Catalog card stored lows | May lag until rollup refresh |

**Safe fix (approved later):** dry-run `update_game_price_rollups` for games where `discarded_stored_low_pln` is set; backup DB first; no snapshot deletion — only rewrite rollup columns from filtered snaps.

**Worth Buy:** thin history caps KUP TERAZ; unverified confirmed flag → POCZEKAJ; junk hist without other signals → wait; trusted hist at current → buy.

---

## C. Cache

| Layer | Finding |
|-------|---------|
| Redis | inactive |
| Nginx HTML | no long-lived HTML cache; static assets `max-age=604800 immutable` |
| Game SSR | already `no-cache, no-store, must-revalidate` |
| `/promocje` (before) | 200 OK, **no** Cache-Control (browser/tool could retain) |
| `/promocje` (after deploy) | `no-cache, must-revalidate` |
| In-app | `HOME_RESP_CACHE_TTL` ~90–120s (region-keyed); `ADMIN_GET_CACHE_TTL` ~60–90s |
| CDN | none observed |
| Service Worker | not used for price HTML |
| Prior “stale 8.99 / KupujPL branding” | Consistent with **tool/browser snapshot or old HTML**, not Redis; HEAD→405; GET game pages already no-store |

---

## D. Tests

| Suite | Result |
|-------|--------|
| `test_trusted_history_and_display` + PE + parity | **pass** (19 with PE V2) |
| `test_engine_unverified_offers` (stale→unverified) | **pass** |
| Full pytest (ignore broken `test_polish_dubbing_model` import) | ~179 pass; intermittent KeyboardInterrupt / a few pre-existing match fixtures when env polluted |
| `PRICE_ENGINE_V2=1` targeted PE regression | **pass** |
| Playwright E2E | **not run this pass** |
| Live price parity (100 games HTTP) | deferred to post-deploy smoke of focus + sample |

---

## E. Production

### Whitelist (deployed files)
- `backend/app/core/price_engine.py`
- `backend/app/core/price_history.py`
- `backend/app/core/game_page_html.py`
- `backend/app/main.py`
- `backend/app/schemas/schemas.py`
- `backend/app/static/game_page.js`
- `backend/app/static/i18n.js`

### Git
- Branch: `fix/quenly-production-stabilization-20261017`
- Checkpoint commits: `cf465b6` (display/history/UI), follow-up poison-price filter on `price_history.py`

### Backup / rollback
- Backup: `/opt/kupujpl-games/backups/pre-price-audit-20261017-211643/` (whitelist file copies + `database.db.bak`, sha256 prefix `4f9db104938b3230`)
- Rollback: restore whitelist files from that backup dir; `systemctl restart kupujpl-games.service`
- **No** full rsync, **no** `rsync --delete`, **no** mass history DELETE

### Post-deploy smoke (API)
| Game | Confirmed best | Unverified cheaper | Trusted lowest |
|------|----------------|--------------------|----------------|
| Satisfactory | IG 97.94 | Gamivo 93.25 stale | 93.25 (stale historical, not anomaly) |
| ULTRAKILL | IG 33.20 | Gamivo 21.43 anomaly | **30.79** (21.43 excluded) |
| Guacamelee | Kinguin 4.80 | Gamivo 2.29 insufficient | **4.80** |
| Rogue Trader | Epic 199.99 | Kinguin 33.46 anomaly; GOG rejected | 199.99 |

`/promocje`: `Cache-Control: no-cache, must-revalidate`; Quenly branding; no Rogue 8.99.

---

## F. Remaining Issues

### Critical
- None blocking confirmed-best for focus games after deploy.

### Medium
- **616** stored historical lows still polluted in DB columns (catalog cards) until approved rollup refresh.
- **~10k** stale in-stock offers need scanner refresh (not a PE rule change).
- Full pytest / Playwright / 100-game live parity not fully green in this session.

### Minor
- `test_polish_dubbing_model` import broken (`_polish_language_flags` missing) — unrelated.
- HEAD requests return 405 (use GET for cache probes).

---

## Final status

**STABLE WITH ISSUES**
