# Quenly — Final Stabilization Report

**Date:** 2026-10-17  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange (unchanged)  
**Server:** 159.195.86.11 (`/opt/kupujpl-games`)  
**Branch:** `fix/quenly-production-stabilization-20261017`

## Final status

**STABLE WITH REMAINING ISSUES**

Production Cozy Orange is up, critical runtime paths work, Site Chat no longer fakes success, Price Engine V2 confirmed/unverified separation is live for Rogue Trader, and automated checks were executed. Full pytest is **not** green (19 pre-existing / API-drift failures remain), so full verification is not claimed.

---

## Problems actually fixed

| Area | Fix |
|------|-----|
| Site Chat fake success | API returns **503** + `available:false`; widget shows unavailable; no message persistence |
| Telegram bot import crash path | Soft-import `app.core.site_chat` (module still absent) |
| Rogue Trader / PE V2 display | Confirmed best stays official; excluded in-stock keyshops exposed as **`unverified_offers`** + UI section |
| F2P CTA | `game_interactive_html` renders `free_play_url` / `Graj za darmo` again |
| G2A scanner lock | `_G2A_LOCK` changed `Lock` → `RLock` (re-entrancy) |
| Pytest `db` fixture | Restored `backend/tests/conftest.py` |
| PE / Offer model drift for tests | Added `money()`, evaluate compat, Offer V2 columns on model, `_OFFER_V2_COLUMNS` |

Design / DNS / canonical / scanners (except G2A RLock) / full rsync: **not changed**.

---

## Production hotfixes moved into Git

Synced from live production into the stabilization branch, then committed:

- Price Engine V2 stack (`price_engine.py`, `price_engine_config.py`, matching/freshness/quality helpers)
- Offer selection / quality / store classification dependencies
- Cozy page + favicon/brand assets
- Site chat honest-disable + unverified offers plumbing

### Commit hashes

| Hash | Message |
|------|---------|
| `04ccd67` | Stabilize Quenly production: unify kupujpl SEO host, FX/SSR hotfixes, chat stub |
| `5a596ae` | Sync production Price Engine V2 modules and offer selection hotfixes into Git |
| `2ba515c` | Disable Site Chat honestly with 503 API and unavailable widget (no fake success) |
| `0d41699` | Surface Price Engine excluded keyshops as separate unverified offers UI |
| `6e2e1c7` | Ship Quenly Q favicon and brand assets across static pages |
| `5515e88` | Restore pytest db fixture and expand production read-only Playwright coverage |
| `b86fa50` | Fix F2P free-play CTA, G2A reentrant lock, Offer V2 model fields, and pytest PE compat |
| `d09f4ad` | Add final stabilization Playwright and Lighthouse result artifacts |

---

## Site Chat status

**Unavailable (honest).**

- Components: `site-chat.js`, `/api/site-chat`, `site_chat_routes.py`, `telegram_bot` soft-import of missing `app.core.site_chat`
- Intended architecture: public widget ↔ API ↔ DB messages ↔ Telegram owner replies
- Reality: `app.core.site_chat` **not deployed**; full backend not restored
- UX: widget opens with explicit unavailable copy; POST/GET → **503**, `ok:false`
- Tests: `tests/test_site_chat_unavailable.py` (pass)

---

## Price Engine V2 — Rogue Trader

**Game:** `Warhammer 40,000: Rogue Trader` (`id=1602`, slug `warhammer-40000-rogue-trader-2186680`)

| Offer | Price | Stock | Region | Result |
|-------|------:|:-----:|--------|--------|
| GOG | 8.99 | yes | global | **excluded** `not_eligible` (absurd vs Steam; wrong-SKU class) |
| Kinguin | 33.46 | yes | eu | **excluded** `url_invalid` / mismatch |
| Kinguin | 36.78 | yes | unknown | filtered / not in PE confirmed set |
| CDKeys / IG / G2A | ~31–41 | no | — | OOS, not shown as confirmed |
| Fanatical | 74.90 | no | global | OOS |
| Steam | 199.99 | yes | global | stale / reference |
| Epic Games | 199.99 | yes | global | **confirmed best** |

- `KEYSHOP_CONFIRMED_STEAM_RATIO=0.22` → floor ≈ **44.00 PLN** vs Steam 199.99  
- Confirmed hero price remains **199.99 PLN (Epic Games)** — rules **not** loosened  
- API now returns `unverified_offers` separately (live: GOG 8.99, Kinguin 33.46) with UI label **Oferty niezweryfikowane**  
- Production DB was **not** mutated to force outcomes  

---

## Pytest

**Environment:** `/opt/kupujpl-games/backend` venv  
**Log:** `/tmp/pytest-final-20261017.txt`

```
19 failed, 156 passed, 1001 warnings in ~6.1s
```

`db` fixture restored; collection no longer dies on missing `db`.

Remaining failures (not hidden):

- `test_game_sitemap.py` (6)
- `test_offer_integrity.py` (3)
- `test_polish_dubbing_model.py` (2) — model columns missing
- `test_price_engine.py` (5) — tests assume richer Session-first / verification API than production module
- `test_scanner_optimization.py` (3)

New/stabilization tests that pass: site chat unavailable, unverified offers helper, F2P CTA, G2A RLock, edition matching (updated fixtures).

---

## Playwright

1. Existing smoke: `tests/e2e_prod_smoke_cozy.py` (prior stabilization)  
2. Expanded read-only functional: `tests/e2e_prod_functional_cozy.py`  
   - Artifact: `docs/e2e-prod-functional-20261017.json`  
   - **PASS** (search, sort/filter chips, game open, offers API, confirmed vs unverified, auth pages read-only, favorite/alert UI markers, mobile nav, no critical JS errors)  
   - Production tests are **read-only** (no favorites/alerts writes)

---

## Lighthouse (production)

Artifacts:

- `docs/lighthouse-desktop-20261017.json`
- `docs/lighthouse-mobile-20261017.json`

| Form factor | Perf | A11y | BP | SEO | LCP | CLS | TTFB | TBT |
|-------------|-----:|-----:|---:|----:|----:|----:|-----:|----:|
| Desktop | 71 | 97 | 96 | 100 | 2.3 s | 0.126 | ~30 ms | 0 ms |
| Mobile | 58 | 96 | 96 | 100 | 10.0 s | 0 | ~40 ms | 110 ms |

INP: no field data in these lab runs (`interaction-to-next-paint` not populated).

No Cozy Orange redesign applied for Lighthouse. Mobile LCP remains an open performance issue.

---

## Scanners

- Independent scanner units still active under systemd (`steam`, `gog`, `epic`, `g2a`, …)  
- Minimal change only: **G2A `RLock`** for re-entrancy  
- No scanner rewrite / no full redeploy of parser fleet  

---

## Production HTTP smoke

| URL | Result |
|-----|--------|
| `/games/` | 200 |
| `/games/api/fx` | 200 |
| `/games/api/site-chat` | **503** (expected) |
| `/games/api/games/warhammer-40000-rogue-trader-2186680` | 200; best 199.99; `unverified_offers` present |
| `/games/gra/warhammer-40000-rogue-trader-2186680` | 200 |
| Service `kupujpl-games` | **active** |

---

## Backup

**Path:** `/opt/backups/quenly-final-stabilization-20261017-161505`  
**Integrity:** `PRAGMA integrity_check` → `ok`  
Contains: `app/`, `backend.env`, `database.backup.db`, `integrity.txt`, `pre-deploy-hashes.txt`

### Rollback procedure

1. `systemctl stop kupujpl-games.service`  
2. Restore whitelist files from backup `app/` (or copy entire `app/` tree) over `/opt/kupujpl-games/backend/app/`  
3. If DB restore needed: stop writers, restore `database.backup.db` → `database.db` via SQLite backup/copy with WAL awareness  
4. `systemctl start kupujpl-games.service`  
5. Smoke: `/games/`, `/api/fx`, one game page, `/api/site-chat`  

Do **not** `git reset --hard` on production.

---

## Deploy notes (this pass)

Minimal whitelist applied after backup (no full rsync, no DNS, no canonical rewrite):

- `main.py`, `schemas.py`, `site_chat_routes.py`, `telegram_bot.py`
- `price_engine.py`, `game_page_html.py`, `game_page.js`, `site-chat.js`
- `models.py`, `schema_migrate.py`, `g2a_parser.py` (compat / RLock)

---

## Unresolved issues

1. Full `app.core.site_chat` backend still missing — chat remains unavailable by design until implemented  
2. Pytest: **19 failures** (sitemap / offer integrity / polish dubbing / price_engine test API / scanner optimization)  
3. Mobile Lighthouse Performance **58**, LCP ~10 s  
4. Desktop CLS **0.126** above ideal  
5. Some keyshop rows remain stale/OOS; PE correctly keeps them out of confirmed best  
6. GOG 8.99 for Rogue Trader is a known bad match class — shown only under unverified  

---

## Verdict

**STABLE WITH REMAINING ISSUES**

Cozy Orange production is preserved and critical user-facing defects from the prior report were addressed without a full redeploy. Full green pytest + strong mobile LCP would be required before **STABLE — FULLY VERIFIED**.
