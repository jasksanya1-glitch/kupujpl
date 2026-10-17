# Quenly — Production Stabilization Report

**Date:** 2026-10-17 (CEST)  
**Server:** `159.195.86.11`  
**URL:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange (unchanged design)  
**Final verdict:** **STABLE WITH ISSUES**

---

## 1. Production state

| Item | Value |
|------|-------|
| Git HEAD (unchanged) | `af244b3acc47a64669d85150d70c2fe5eb38d8cf` |
| Branch on server | `fix/technical-seo-indexing` (dirty working tree) |
| Local stabilization branch | `fix/quenly-production-stabilization-20261017` |
| Service | `kupujpl-games` active |
| WorkingDirectory | `/opt/kupujpl-games/backend` |
| `PRICE_ENGINE_V2` | `1` |
| Scanners | steam/gog/epic/g2a/… **active** |
| Cozy assets | Present (`theme-cozy-orange-app.css?v=17`, Quenly logo, hero) |

### Root cause of SEO split (fixed)

| Source | `GAMES_BASE_URL` |
|--------|------------------|
| `/opt/kupujpl-games/backend/.env` | was `https://quenly.pl/games` |
| `/opt/kupujpl-games/.env` (systemd last) | `https://kupujpl.pl/games` |
| Static `index.html` canonical | was hardcoded `quenly.pl` |
| SSR game pages | used process env → `kupujpl.pl` |

Result before fix: home claimed `quenly.pl`, game pages claimed `kupujpl.pl`.

### Runtime patches reconciled into Git branch

- `game_page_html.py` — `is_free` + related kwargs, Cozy skin, Quenly logo  
- `currency_pln.py` — `fx_snapshot()`  
- `site_config.py` — default `SITE_ORIGIN` → `https://kupujpl.pl/games`  
- `store_classification.py` — restored on production (was missing; broke local pytest)  
- Static SEO hosts on home/legal pages → `kupujpl.pl`  
- `/api/site-chat` stub handlers on production `main.py` (module `site_chat_routes.py` in Git)

**Not committed:** secrets, `.env`, DB, full production `main.py` (only stub concept mirrored in `site_chat_routes.py`).

---

## 2. Fixed bugs

### A. `game_interactive_html` unexpected kwargs → HTTP 500

- **Root cause:** production `main.py` passed `is_free` / freshness / worth-buy kwargs; older signature rejected them.  
- **File:** `backend/app/core/game_page_html.py`  
- **Fix:** accept kwargs (compat tuple); keep Cozy CSS/body.  
- **Test:** `tests/test_game_page_html_kwargs.py` + live `/gra/{slug}` 200  
- **Result:** Hades II, Cyberpunk, Civ VI, Rogue Trader, Space Marine 2 → **200**

### B. `/api/fx` ImportError

- **Root cause:** `fx_snapshot` missing from `currency_pln.py`  
- **File:** `backend/app/parsers/currency_pln.py`  
- **Fix:** NBP-backed snapshot (USD/EUR/GBP/UAH); keep last cache on NBP failure  
- **Test:** `tests/test_fx_snapshot.py`  
- **Result:** live `/api/fx` → **200** with rates

### C. Conflicting canonical hosts

- **Root cause:** dual `.env` + static HTML hardcoding quenly while SSR used kupujpl  
- **Files:** `index.html`, legal HTML shells, `site_config.py`, `backend/.env` `GAMES_BASE_URL`  
- **Fix:** unify on **`https://kupujpl.pl/games`** for stabilization (brand text remains Quenly)  
- **Result:** home + game SSR + quenly.pl host all emit `kupujpl.pl` canonicals

### D. `/api/site-chat` 404 console noise

- **Root cause:** `site-chat.js` present; `app.core.site_chat` module / routes missing  
- **Fix:** stub GET `{messages:[]}` / POST `{ok:false}` (no persistence)  
- **Result:** endpoint 200; Playwright smoke **PASS**

---

## 3. SEO

| Check | Before | After |
|-------|--------|-------|
| Home canonical | `https://quenly.pl/games/` | `https://kupujpl.pl/games/` |
| Game canonical | `https://kupujpl.pl/games/gra/...` | same host family `kupujpl.pl` |
| Via `quenly.pl` host | mixed | canonical still `kupujpl.pl` |
| robots.txt | OK | OK |
| sitemap index | `kupujpl.pl` locs | aligned with SITE_ORIGIN |
| JSON-LD home | quenly URLs | kupujpl URLs |
| DNS / redirects | unchanged | **not changed** |

Domain migration to quenly.pl remains a separate cutover (`docs/QUENLY-DOMAIN-CUTOVER.md`); this pass only removes contradictory signals during dual-host service.

---

## 4. Price Engine V2

`PRICE_ENGINE_V2=1` preserved.

| Game | API best PLN | SSR | Notes |
|------|-------------:|-----|-------|
| Hades II | 117.00 | 117.00 | OK |
| Cyberpunk 2077 | 59.69 | 59.69 | OK |
| Civilization VI | 188.04 | 188.04 | OK |
| Guacamelee! STCE | 15.74 | 15.74 | OK |
| Rogue Trader | 199.99 | 199.99 | Official Steam/Epic |

### Rogue Trader “8,99 PLN” investigation

- Base game DB still has cheaper **keyshop/historical** rows (e.g. Kinguin ~33 PLN in stock; CDKeys ~31 OOS).  
- PE V2 display correctly surfaces **confirmed official** ~199.99.  
- **8,99 PLN** rows nearby are **other Warhammer titles** (Darktide, Dawn of War, Boltgun, etc. on GOG) — **not** Rogue Trader base game mis-priced.  
- No DB rewrite performed.

Affiliate `/api/go/{id}` links present on SSR.

---

## 5. Tests

| Suite | Result |
|-------|--------|
| `test_fx_snapshot` + `test_game_page_html_kwargs` | **5 passed** |
| Playwright prod read-only (`e2e_prod_smoke_cozy.py`) viewports 360–1920 | **PASS** |
| HTTP smoke (health/fx/gra/SEO) | **PASS** |
| Lighthouse | **Not run** in this pass (time/tooling); recommend follow-up CI job |
| Full pytest | Partial — `test_store_classification_consistency` still needs `db` fixture/`conftest` (module restored; fixture/env incomplete after stash) |

Screenshots: `docs/stabilization-shots-20261017/`

---

## 6. Deployment

| Item | Path / value |
|------|----------------|
| Pre-change backup | `/opt/backups/quenly-stabilization-20261017-20261017-135042/` (SQLite Online Backup + static/core/parsers + `ROLLBACK.sh`) |
| Earlier Cozy backup | `/opt/backups/quenly-cozy-orange-20261017-20261017-035641/` — **POST-theme** snapshot (not pre-Cozy) |
| Pre-theme archives | `…/backups/price-radar-*`, `static-pre-price-radar-*.tgz`, `quenly-migration-*` |
| Release staging | `/opt/kupujpl-games/releases/stabilization-20261017/` |
| Deploy time | ~15:50–16:00 CEST |
| Restart | `kupujpl-games` only |
| Rollback | Not executed |

### Whitelist manifest

- `static/index.html`, `kontakt.html`, `o-nas.html`, `polityka-prywatnosci.html`, `redakcja.html`, `regulamin.html`  
- `core/site_config.py`, `core/game_page_html.py`, `core/store_classification.py`  
- `parsers/currency_pln.py`  
- `backend/.env` line `GAMES_BASE_URL` only  
- inline stub routes in production `main.py` for `/api/site-chat`

**Forbidden ops avoided:** full rsync, `--delete`, DB mutate, DNS change, scanner retune, theme redesign.

### Cozy rollback caveat

`ROLLBACK.sh` in the morning Cozy backup restores **Cozy-era** static/core, not lime/Price Radar. For pre-Cozy UI use older `price-radar-*` backups. Stabilization backup restores **pre-SEO-align** state of this afternoon.

---

## 7. Screenshots

`docs/stabilization-shots-20261017/home-{360,390,430,768,1440,1920}*.png` — Cozy Orange + Quenly branding across breakpoints.

---

## 8. Remaining issues

### Medium

1. Full `site_chat` module still missing (`telegram_bot` imports it) — stub only.  
2. Production Git still dirty with many unrelated runtime patches — needs staged commits / PR series beyond this whitelist.  
3. Dual-host nginx (quenly + kupujpl) remains by design until full cutover.

### Minor

4. `test_store_classification_consistency` needs shared `db` fixture restored.  
5. Lighthouse not executed this pass.  
6. PE V2 hides some in-stock keyshop prices for Rogue Trader (by design) — document for support if users compare raw DB dumps.

### Critical

None open after this pass (no mass 500s on home/gra/fx).

---

## 9. Final verdict

**STABLE WITH ISSUES**

Cozy Orange remains live with Quenly branding; HTTP 500s for game SSR and FX resolved; SEO canonical host unified on `kupujpl.pl`; prices/API/SSR parity verified; scanners active; Playwright read-only smoke passed; hotfixes mirrored into local stabilization branch. Remaining work: full chat module, Git hygiene of long-lived production dirty tree, optional Lighthouse CI, eventual quenly.pl cutover as a separate project.
