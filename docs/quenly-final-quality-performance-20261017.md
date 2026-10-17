# Quenly — Final Quality & Performance (2026-10-17)

**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange (composition preserved)  
**Server:** 159.195.86.11 (`/opt/kupujpl-games`)  
**Branch (controlled Git):** `fix/quenly-production-stabilization-20261017`

## Final status

**STABLE WITH ISSUES**

Production is serving the quality fixes (matching rejected/unverified, PE V2 display tiers, hero/perf assets, nginx gzip/static cache). Full backend pytest is green (180 passed). Playwright production read-only E2E passed. Lighthouse improved materially but mobile LCP / desktop CLS targets are not fully met.

---

## 1. Nineteen pytest failures — root causes & fixes

| Suite | Count | Root cause | Fix |
|-------|------:|------------|-----|
| `test_game_sitemap.py` | 6 | Session polluted by `PRICE_ENGINE_V2=1` from `.env` via `affiliate_feeds.load_dotenv` during collection; Steam fixtures used `example.test` URLs that fail V2 URL allowlist | Force `PRICE_ENGINE_V2=0` in `conftest` (tests opt-in); sitemap helpers use shop-correct URLs |
| `test_offer_integrity.py` | 3 | Flag default polluted; catalog map used fixed `NOW` but `best_offers_map` evaluated with `utcnow` (~27h stale); `best_verified` ignored `stale_warning` | Isolate flag; pass `now=NOW`; restore `best_verified` = confirmed \|\| stale_warning |
| `test_polish_dubbing_model.py` | 2 | ORM missing `has_polish_audio` / `has_polish_interface` despite schema_migrate | Added columns on `Game` model |
| `test_price_engine.py` | 5 | Helpers reused Steam URLs for all shops → `url_invalid`; recommended reason string drift; Fanatical without status became confirmed under V2; `last_check_status=error` ignored | Shop-specific URLs from title; align reason `official_within_tolerance`; too_old fixture for no-verified; exclude error check statuses |
| `test_scanner_optimization.py` | 3 | Missing `_circuit_open_until`, `_redact_feed_url`, feed fail cache; expired env Algolia key returned anyway | Implemented circuit + redaction + fail markers; reject expired env keys |

**Full pytest (production venv):** `180 passed, 0 failed` (`/tmp/pytest-quality-full2.txt`).

Regression added: `tests/test_game_matching_rejected.py` (Dawn of War vs Rogue Trader, edition/DLC, private URL, Awin allowlist).

---

## 2. Game matching — Rogue Trader

**Live evaluation (id=1602) after deploy:**

| Offer | Price | Display tier | Notes |
|-------|------:|--------------|-------|
| Epic Games | 199.99 | **confirmed** | Best confirmed |
| Steam | 199.99 | stale / unverified band | Identity OK, freshness warning |
| Kinguin | 33.46 | **unverified** | Awin URL + `kp_title` = Rogue Trader EU; price below Steam ratio → needs review, not wrong-title reject |
| GOG | 8.99 | **rejected** | URL is **Dawn of War Anniversary Edition** — franchise sibling false-positive fixed in `title_mismatch` / edition markers |

**Rules implemented:**

- **CONFIRMED** — PE confirmed bucket (hero / catalog best).
- **UNVERIFIED** — identity-plausible excluded rows (e.g. keyshop `price_anomaly`); shown with warning; **not** used as best price.
- **REJECTED** — wrong title/edition/SKU, bad URL, official absurd undercut; **omitted** from `unverified_offers` (not buyable). Admin: `rejected_offers_from_result()`.

API smoke: `unverified_offers` = Kinguin only; GOG 8.99 absent. Confirmed best remains **199.99 Epic**. Confirmed PE ratio rules were **not** loosened.

Kinguin check: affiliate `awin1.com` link is valid for shop allowlist; fragment title matches Rogue Trader; offer remains unverified due to price anomaly vs Steam — not promoted to confirmed.

---

## 3. Mobile / desktop performance

| Metric | Before | After (final paired run) | Target |
|--------|--------|---------------------------|--------|
| Mobile Performance | **58** | **83** | ≥85 |
| Mobile LCP | **~10.0 s** | **~3.6 s** | ≤2.5 s |
| Mobile CLS | 0 | **0.068** | <0.1 |
| Desktop Performance | **71** | **86** | ≥90 |
| Desktop LCP | 2.3 s | **1.1 s** | — |
| Desktop CLS | 0.126 | **0.206** | <0.1 |

**Best intermediate mobile run (same day):** Performance **84**, LCP **3.5 s**, CLS **0.053**.  
**Best intermediate desktop run:** Performance **90**, LCP **1.2 s**, CLS **0.119**.

### What changed

- Hero: AVIF/WebP/JPEG `srcset` + preload (was 340 KiB full JPG @ 2161px).
- Logo + QP buy button: resized WebP/PNG.
- nginx: enabled `gzip_types` + `gzip_proxied`; `/games/static/` served from disk with 7d cache.
- Deferred non-critical JS; reserved hero aspect-ratio / mobile layout without `-40%` overlap.

### Residual causes (honest)

- Mobile LCP still >2.5 s (catalog Steam headers + remaining CSS/JS; simulated Slow 4G).
- Desktop CLS still ≥0.1 (catalog/card paint after hero; not fully eliminated).
- Unused CSS from multi-layout stylesheets remains.

Artifacts: `docs/lighthouse-*-20261017.json`, `docs/lighthouse-*-final-20261017.json`.

---

## 4. Git / production consistency

- Controlled commits prepared on `fix/quenly-production-stabilization-20261017` (see hashes below after commit).
- Runtime files deployed surgically under `/opt/kupujpl-games` (not full rsync).
- Release manifest: `/opt/backups/quenly-quality-release-20261017-170753/`  
  - `WHITELIST.txt`, `runtime-sha256.txt`, nginx snapshots, `rollback-whitelist.sh`
- Pre-quality code snapshot still available: `/opt/backups/quenly-final-stabilization-20261017-161505`
- Post-patch quality file snapshot: `/opt/backups/quenly-quality-20261017-165559`

**Note:** Production working tree may also contain unrelated dirty files from other ops branches; quality deploy was whitelist-only.

---

## 5. Safe rollback

- Point restore: use `WHITELIST.txt` + known-good hashes from stabilization backup; **do not** `git reset --hard` on production.
- nginx rollback: restore `kupujpl-games.nginx` + `nginx.conf` from the quality-release backup dir, then `nginx -t && systemctl reload nginx`.
- Dry-run: whitelist integrity check `missing=0` at manifest creation.
- DB rollback: **not** performed / not required.

---

## 6. Site Chat

Still honestly **unavailable** (503 / `available:false`). No new chat backend. E2E confirms widget does not claim success; no interference with catalog/game flows.

---

## 7. Playwright E2E

Artifact: `docs/e2e-prod-functional-quality-20261017.json` — **PASS** (read-only production).

Covers home, search, sort/filter presence, Rogue Trader game page, confirmed vs unverified API, GOG 8.99 not buyable, auth pages, mobile nav, site chat, JS console.

---

## 8. Production patch checklist

1. Git checkpoint on stabilization branch (this pass).  
2. Backups under `/opt/backups/quenly-quality-*`.  
3. Manifest integrity OK.  
4. Whitelist deploy of PE/matching/static/perf files.  
5. `systemctl restart kupujpl-games` after PE/matching.  
6. HTTP/API smoke + Playwright + Lighthouse re-run.  
7. Price Engine V2: Rogue Trader confirmed Epic 199.99.

DNS / canonical / scanners: unchanged (except existing G2A RLock from prior pass).

---

## Unresolved

- Mobile Performance / LCP short of stretch goals (83 / 3.6 s vs 85 / 2.5 s).
- Desktop CLS regression vs target (<0.1); desktop Perf 86 vs 90.
- Production Git branch name on server may differ from local stabilization branch — use whitelist + hashes, not branch tip alone.
- Site Chat backend still absent (intentional for this task).

---

## Git commit hashes

| Hash | Message |
|------|---------|
| `cbac0ee` | Fix Quenly quality: PE matching tiers, green pytest, mobile LCP assets |
| `b7d90c2` | Place news and deal-hunter panel below the desktop game catalog (prior) |

Full: `cbac0eea883950e63aefa65aa57ff609b125e9b6`

### Deployed files (whitelist)

See `/opt/backups/quenly-quality-release-20261017-170753/WHITELIST.txt` and `runtime-sha256.txt`.
