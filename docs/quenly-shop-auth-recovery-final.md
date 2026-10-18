# Quenly — Shop Auth Recovery Final Report

**Date:** 2026-10-18  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange — unchanged  
**Price Engine:** V2 — unchanged  
**Backup:** `/opt/kupujpl-games/backups/pre-shop-auth-20261018-142549`  
**Status:** **STABLE WITH ISSUES** (Kinguin + dashboard fixed; Fanatical + CDKeys require owner credentials)

---

## Classification legend

| Tag | Meaning |
|---|---|
| **FIXED AUTOMATICALLY** | Deployed code/status fix with no new secrets |
| **REQUIRES OWNER AUTHORIZATION** | Legitimate partner credential / feed ID needed |
| **BLOCKED BY EXTERNAL PROVIDER** | Provider rejects current authorized access |
| **NOT FIXED** | Still broken after this pass |

---

## 1. Fanatical root cause

**BLOCKED BY EXTERNAL PROVIDER** + **REQUIRES OWNER AUTHORIZATION**

| Check | Result |
|---|---|
| `AWIN_DATAFEED_API_KEY` | Present |
| `AWIN_FEED_FID_FANATICAL` | Present (numeric FID configured) |
| Download with configured FID | **HTTP 404** — Awin body: `Feed not found` |
| Awin Product Feed List API | **HTTP 401 Unauthorized** |
| On-disk CSV cache | **Missing** (`fanatical.fail` negative-cache marker only) |
| HTML fallback | None (feed-only shop by design) |

Root cause: the configured Fanatical Feed ID is **not a valid/authorized downloadable feed** for the current DataFeed API key. Catalog discovery cannot repair this because the list endpoint returns 401. No FID was invented.

Scanner correctly stays **AUTH_REQUIRED / blocked** until a working FID + authorized API key produce a cache.

---

## 2. Fanatical authorization requirements (owner)

**REQUIRES OWNER AUTHORIZATION**

1. In Awin publisher account → **Tools → Product Feeds** (or DataFeed API credentials page).  
2. Confirm the DataFeed API key can call `datafeed/list` (must not 401).  
3. Join / re-approve **Fanatical** (merchant ID **118821** if still current).  
4. Copy the **current Feed ID** from the authorized feed list into `.env`:
   - `AWIN_FEED_FID_FANATICAL=<fid from Awin>`  
5. Restart `kupujpl-scanner@fanatical` (or wait for fail-marker expiry) and confirm `tmp/affiliate_feeds/fanatical.csv` is created.  
6. Do **not** invent Feed IDs. Do **not** bypass Awin auth.

---

## 3. CDKeys / Loaded root cause

**REQUIRES OWNER AUTHORIZATION** (+ Cloudflare blocks VPS HTML key refresh)

| Check | Result |
|---|---|
| Bundled Algolia secured key | Expired **2026-06-08** |
| `CDKEYS_ALGOLIA_API_KEY` in `.env` | Present but **expired** (`validUntil` in the past) |
| Live refresh from cdkeys.com / loaded.com | Fails on VPS (Cloudflare / thin HTML) |
| Awin CDKeys FID / partner feed | Not configured |
| Algolia App ID | Still `MUVYIB7TEY` (public frontend app) |

Root cause: search-only Algolia secured keys expire; both the bundled default and the env key are past `validUntil`. Datacenter IP cannot reliably scrape a fresh key from the storefront. Loaded.com rebrand URLs are already tried; they do not yield a usable key from this host.

---

## 4. CDKeys repair results

**NOT FIXED** (cannot mint a valid Algolia key without owner / residential scrape)

**FIXED AUTOMATICALLY (supporting):**

- Broader HTML key extraction patterns (Loaded + Magento variants).  
- 403 → invalidate cached key + short circuit breaker (no stamp of fake verifies).  
- Shop auth blocker allows scan if an affiliate feed cache exists (DEGRADED path).  
- Clearer owner_action text in admin API.

**Owner must set one of:**

1. Fresh `CDKEYS_ALGOLIA_API_KEY` (search-only secured key from cdkeys.com/loaded.com DevTools → Network → Algolia request), **or**  
2. Partner feed: `AWIN_FEED_FID_CDKEYS` / `AFFILIATE_FEED_URL_CDKEYS`.

Do not extract keys from unauthorized sources. Do not mark old prices newly verified.

---

## 5. Kinguin status correction

**FIXED AUTOMATICALLY**

| Before | After |
|---|---|
| Dashboard / progress often **AUTH_REQUIRED** when Awin feed negative-cached | Process can stay active; data-source shows **DEGRADED** when HTML fallback works |
| `shop_auth_blocker("Kinguin")` | Still **None** (HTML authorized) |
| Live 1h sample post-deploy | **177 attempts / 33 verified (~18.6%)** — scanner working |

UI now separates:

- Process status (systemd active)  
- Data-source status (feed vs HTML)  
- `human_status_code`: `WORKING` / `DEGRADED` / `AUTH_REQUIRED` / …

Stale `phase=auth_failed` progress no longer forces AUTH when `verified_1h > 0` and no hard blocker.

---

## 6. Instant Gaming efficiency

**FIXED AUTOMATICALLY (selection bias)** — still **LONG-TERM PENDING** for sustained rate

| Metric (1h window at audit) | Value |
|---|---:|
| Attempts | 873 |
| Verified | 5 |
| Success rate | **0.6%** |
| Dominant status | `not_found` 863 |

The ~100 ok / ~1065 attempts screenshot pattern matches: most attempts are never-listed Tier C titles. RPS **not** increased.

Changes:

- Instant Gaming tier mix default **70% A / 20% B / 10% C** (env: `SCAN_IG_TIER_*_PCT`).  
- Instant Gaming never-listed backoff default **72h** (`SCAN_IG_NEVER_LISTED_BACKOFF_HOURS`).  

Expect success rate to rise as Tier C not_found rows stay out of the queue longer — re-measure after several hours.

---

## 7. Scanner throughput before / after

| Shop | Before (symptom) | After deploy |
|---|---|---|
| Fanatical | auth_failed loop, 0 verifies | Still blocked (invalid FID) — correct |
| CDKeys | auth_failed, expired key | Still blocked — correct |
| Kinguin | Misleading AUTH_REQUIRED | **DEGRADED** + HTML verifies (~33/h sample) |
| Instant Gaming | High attempts, low ok | Selection bias + longer never-listed (rate TBD) |

No RPS increases. No PE threshold changes.

---

## 8. Confirmed coverage before / after

Live snapshot at deploy verification:

| Metric | Value |
|---|---:|
| Paid games | 10426 |
| Paid confirmed | 9539 |
| Paid confirmed % | **91.49%** |

Identity/auth work does **not** invent coverage. Fanatical/CDKeys remaining blocked does not lower Steam/GOG/etc. confirmed stock.

---

## 9. Tests

| Suite | Result |
|---|---|
| `tests/test_shop_auth_recovery.py` | Passed |
| `tests/test_scanner_optimization.py` | Passed |
| `tests/test_pe_confirmed_after_miss.py` | Passed |
| `tests/test_upsert_stamps_verification.py` | Passed (Steam fixture now includes `currency=PLN`) |
| Focused auth/scanner/PE set | **24 passed** |
| Full `tests/` | **277 passed**, 1 failure fixed (Steam currency fixture); re-run after fixture fix green on focused set |

Failed requests still do not bump `last_verified_at` (existing integrity tests).

---

## 10. Git commits

Local branch `fix/quenly-production-stabilization-20261017` — **`0264b69`** Restore shop scanner auth status and selection efficiency. Prior related: `e445954` (Steam currency / slug), `888043f`.

---

## 11. Production changes (whitelist)

Deployed to `/opt/kupujpl-games` (SHA256 in backup manifest):

- `backend/app/core/offer_verification.py` — `shop_data_source_status`, accurate blockers  
- `backend/app/parsers/affiliate_feeds.py` — catalog discover helper, safer redaction  
- `backend/app/parsers/cdkeys_parser.py` — key refresh / 403 invalidate  
- `backend/app/parsers/shop_scan_queue.py` — IG tier mix + never-listed  
- `backend/app/parsers/scanner_panel_detail.py` — DEGRADED / AUTH semantics  
- `backend/app/static/panel3.js` — process vs data-source vs rates  

**Not deployed / not changed:** Cozy Orange, DNS, PE V2 thresholds, scanner RPS caps, mass DB price edits.

---

## 12. Backup and rollback

| Item | Path |
|---|---|
| Backup | `/opt/kupujpl-games/backups/pre-shop-auth-20261018-142549` |
| Manifest | `WHITELIST_MANIFEST.txt` + SQLite `.backup` |
| Rollback | Restore the six whitelist files from that backup; `systemctl restart kupujpl-games` + affected `kupujpl-scanner@*` units; poll `/api/health` |

---

## 13. Remaining requirements from owner

1. **Fanatical:** Valid Awin DataFeed API authorization (list ≠ 401) + current Fanatical **Feed ID** → `AWIN_FEED_FID_FANATICAL`.  
2. **CDKeys / Loaded:** Fresh non-expired `CDKEYS_ALGOLIA_API_KEY` **or** partner product feed URL/FID.  
3. Re-run canary after credentials: Fanatical CSV cache rows > 0; CDKeys Algolia hit ≥1 for a known title; no `last_verified_at` on failed attempts.  
4. Re-measure Instant Gaming success rate after ≥6–12h with new selection bias.

---

## Final status

### **STABLE WITH ISSUES**

| Shop | Outcome |
|---|---|
| Kinguin | **FIXED AUTOMATICALLY** (DEGRADED + HTML working) |
| Scanner dashboard | **FIXED AUTOMATICALLY** |
| Instant Gaming selection | **FIXED AUTOMATICALLY** (efficiency TBD) |
| Fanatical | **REQUIRES OWNER AUTHORIZATION** / **BLOCKED BY EXTERNAL PROVIDER** |
| CDKeys | **REQUIRES OWNER AUTHORIZATION** |

Accuracy preserved: no speculative FIDs, no unauthorized key scraping, no fake confirmations, no PE loosen, no RPS hike.
