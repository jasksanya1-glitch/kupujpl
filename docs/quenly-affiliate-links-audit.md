# Quenly — Full Affiliate Links & Commission Audit

**Date:** 2026-10-18  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Evidence:** `/opt/kupujpl-games/backend/tmp/affiliate_links_audit.json`  
**Backup:** `/opt/kupujpl-games/backups/pre-affiliate-audit-20261018-144449`  
**Theme / PE / RPS:** Cozy Orange unchanged · PE V2 unchanged · scanner RPS unchanged  

**Important:** This audit verifies Quenly **forms and preserves partner tracking** on the buy path (`/api/go/{offer_id}` → `resolve_outbound_url`). It does **not** claim that commissions were paid. Partner-dashboard confirmation is required for that. Status **WORKING LINK — TRACKING CONFIGURED** is reserved for dashboard-proven accrual (none claimed this pass).

---

## How Kup / Kup teraz links work

| Layer | Behavior |
|---|---|
| SSR game page | Buy href = `{SITE}/api/go/{offer.id}` (`game_page_html.py`) |
| SPA modal (`app.js`) | `offerGoUrl` → `api/go/{id}` (not raw shop URL) |
| Endpoint | `GET /api/go/{offer_id}` → `resolve_outbound_url` → **302** to destination |
| Awin | Server unwraps `awin1.com` / `awstrack.me` → merchant URL with `awc=` (ad-blocker safe) |
| Logging | `log_affiliate_click` (never blocks redirect) |

Sample size: **20 in-stock offers per shop** (when available) + **5 live `/api/go` redirect probes** per shop. SSR spot-check: `hades-ii` HTML contains `/api/go/` links and Kup CTA.

---

## Status legend

| Status | Meaning |
|---|---|
| **WORKING LINK — ATTRIBUTION UNVERIFIED** | Product opens; tracking params / Awin `awc` present on outbound. Commission **not** proven. |
| **DIRECT LINK — NO AFFILIATE TRACKING** | Valid shop URL; Quenly has **no** partner ID configured for this shop. |
| **BROKEN LINK** | Redirect fails or destination unusable. |
| **AUTH REQUIRED** | Shop scanner auth blocks new data (clicks on existing offers may still work). |
| **WORKING LINK — TRACKING CONFIGURED** | Not used here without partner-dashboard proof. |

---

## Per-shop results

### Steam / Steam US

| Metric | Steam | Steam US |
|---|---:|---:|
| In-stock offers | 10415 | 1014 |
| Sample | 20 | 20 |
| Affiliate stored | 0 | 0 |
| Direct stored | 20 | 20 |
| Outbound tracking | 0 | 0 |
| Broken redirects | 0 | 0 |
| Wrong URL / product | 0 | 0 |
| Tracking ID present | No | No |
| Product opens | Yes (store.steampowered.com/app/{id}) | Yes |
| Extra auth | No | No |
| Commission confirmed | **No** | **No** |
| **Status** | **DIRECT LINK — NO AFFILIATE TRACKING** | **DIRECT LINK — NO AFFILIATE TRACKING** |

No Steam affiliate program wired in Quenly (by design).

---

### GOG

| Metric | Value |
|---|---:|
| In-stock offers | 1623 |
| Sample / affiliate / direct | 20 / 0 / 20 |
| Outbound tracking | 0 |
| Broken redirects | 0 |
| Product hint OK | 20/20 |
| `GOG_AFFILIATE_CODE` | **Not set** |
| **Status** | **DIRECT LINK — NO AFFILIATE TRACKING** |

Code path appends `?pp=` when env is set. Owner must supply `GOG_AFFILIATE_CODE` from GOG Galaxy partner portal. No IDs invented.

---

### Epic Games

| Metric | Value |
|---|---:|
| In-stock offers | 1937 |
| Sample / direct | 20 / 20 |
| Outbound tracking | 0 |
| Broken redirects | 0 |
| **Status** | **DIRECT LINK — NO AFFILIATE TRACKING** |

No Epic affiliate ID in Quenly. Redirects 302 → `store.epicgames.com` OK. (Slug-token SKU heuristic is weak for Epic DLC URLs; redirects still land on Epic store.)

---

### G2A

| Metric | Value |
|---|---:|
| In-stock offers | 3982 |
| Sample / affiliate stored | 20 / 20 |
| Outbound tracking | 20/20 (`gname` + often `awc`) |
| Broken redirects | 0 |
| Product hint OK | 20/20 |
| Config | `G2A_GOLDMINE_GNAME` set |
| **Status** | **WORKING LINK — ATTRIBUTION UNVERIFIED** |

---

### Gamivo

| Metric | Value |
|---|---:|
| In-stock offers | 2099 |
| Sample / affiliate | 20 / 20 |
| Outbound tracking | 20/20 (`glv`) |
| Broken redirects | 0 |
| Config | `GAMIVO_REF` set |
| **Status** | **WORKING LINK — ATTRIBUTION UNVERIFIED** |

---

### Kinguin (HTML fallback path)

| Metric | Value |
|---|---:|
| In-stock offers | 3393 |
| Sample stored class | **20 direct** (HTML scrape stores merchant URL) |
| Outbound tracking | **20/20** after Awin wrap + unwrap (`awc`, utm_*) |
| Broken redirects | 0 |
| Still on awin1.com in browser | **0** (server unwrap) |
| Product hint OK | 20/20 |
| Feed auth | Awin feed download may be degraded; **clicks still tracked** |
| **Status** | **WORKING LINK — ATTRIBUTION UNVERIFIED** |

Affiliate ID is **not** lost on Quenly redirect: `/api/go` → Awin cread → unwrap → `kinguin.net?...&awc=...`.

---

### Instant Gaming

| Metric | Value |
|---|---:|
| In-stock offers | 1800 |
| Sample / affiliate | 20 / 20 |
| Outbound tracking | 20/20 (`igr`) |
| Broken redirects | 0 |
| Config | `INSTANT_GAMING_REF` set |
| **Status** | **WORKING LINK — ATTRIBUTION UNVERIFIED** |

---

### CDKeys / Loaded

| Metric | Value |
|---|---:|
| In-stock offers | 898 |
| Sample / direct | 20 / 20 |
| Outbound tracking | **0** |
| Broken redirects | 0 |
| Product opens | Yes (cdkeys.com) |
| `CDKEYS_AFFILIATE_REF` | **Not set** |
| Scanner auth | Algolia key expired (new verifies blocked) |
| **Status** | **DIRECT LINK — NO AFFILIATE TRACKING** |

Existing offers open the right product but **without** `?ref=` partner param. Owner must set `CDKEYS_AFFILIATE_REF` (and fix Algolia for new prices).

---

### Fanatical (Awin)

| Metric | Value |
|---|---:|
| In-stock offers | 283 |
| Sample stored | 20 Awin deep links |
| Outbound tracking | 20/20 (`awc` on fanatical.com) |
| Broken redirects | 0 |
| Still awin1 in browser | 0 |
| Product hint OK | 20/20 |
| Feed download | **AUTH / invalid FID** (new feed refresh blocked) |
| **Status** | **WORKING LINK — ATTRIBUTION UNVERIFIED** (existing offers) |

Cached/historical Fanatical offers still unwrap correctly with Awin attribution. New catalog ingest remains blocked until a valid Feed ID is provided (see shop-auth report).

---

### Eneba / Humble Store

| Shop | In-stock | Status |
|---|---:|---|
| Eneba | 0 | No active offers — N/A |
| Humble Store | 0 | No active offers — N/A |

---

## Summary table

| Shop | Offers | Aff. stored | Direct | Track out | Broken redir | Tracking ID | Product OK | Extra auth | Commission | Status |
|---|---:|---:|---:|---:|---:|---|---|---|---|---|
| Steam | 10415 | 0 | 20 | 0 | 0 | No | Yes | No | No | DIRECT — NO AFFILIATE |
| Steam US | 1014 | 0 | 20 | 0 | 0 | No | Yes | No | No | DIRECT — NO AFFILIATE |
| GOG | 1623 | 0 | 20 | 0 | 0 | No | Yes | No | No | DIRECT — NO AFFILIATE |
| Epic | 1937 | 0 | 20 | 0 | 0 | No | Yes* | No | No | DIRECT — NO AFFILIATE |
| G2A | 3982 | 20 | 0 | 20 | 0 | Yes | Yes | No | Unverified | ATTRIBUTION UNVERIFIED |
| Gamivo | 2099 | 20 | 0 | 20 | 0 | Yes | Yes | No | Unverified | ATTRIBUTION UNVERIFIED |
| Kinguin | 3393 | 0 | 20 | 20 | 0 | Yes (awc) | Yes | Feed degraded | Unverified | ATTRIBUTION UNVERIFIED |
| Instant Gaming | 1800 | 20 | 0 | 20 | 0 | Yes (igr) | Yes | No | Unverified | ATTRIBUTION UNVERIFIED |
| CDKeys | 898 | 0 | 20 | 0 | 0 | No | Yes | Algolia expired | No | DIRECT — NO AFFILIATE |
| Fanatical | 283 | 20 | 0 | 20 | 0 | Yes (awc) | Yes | Feed FID invalid | Unverified | ATTRIBUTION UNVERIFIED |
| Eneba | 0 | — | — | — | — | — | — | — | — | N/A |
| Humble | 0 | — | — | — | — | — | — | — | — | N/A |

\*Epic SKU path tokens often differ from Steam slugs; HTTP redirect still reaches Epic store.

---

## What was fixed

1. **`affiliate_link_configured`** — treats Awin click-wrap (publisher ID + MID) as configured for Kinguin / Fanatical / G2A / Eneba, not only empty `KINGUIN_AFFILIATE_REF`.  
2. **`affiliate_env_status`** — loads `.env`, reports `awin_click_wrap_configured` vs feed download, and `click_tracking` per shop (admin no longer shows Kinguin/Fanatical as “missing” when clicks wrap correctly).  
3. **Tests** — `test_affiliate_outbound.py` covers Awin-configured shops and missing GOG/CDKeys.  
4. **No affiliate IDs invented.** No real purchases. No secrets in this report.

Deploy whitelist: `affiliate.py`, `affiliate_config.py` → backup `pre-affiliate-audit-20261018-144449`.

---

## Owner actions (no code speculation)

1. Set `GOG_AFFILIATE_CODE` if GOG partner program is approved.  
2. Set `CDKEYS_AFFILIATE_REF` (and fresh Algolia key for scanning).  
3. Confirm in **Awin / G2A / IG / Gamivo dashboards** that clicks convert to commissions (required before any “TRACKING CONFIGURED / commission confirmed” claim).  
4. Fanatical feed FID repair remains separate (shop-auth report) — does not invalidate existing offer click unwrap.

---

## Final verdict

Buy buttons correctly route through **`/api/go/{offer_id}`**. Partner tracking is present for **G2A, Gamivo, Instant Gaming, Kinguin (Awin wrap), Fanatical (cached Awin)**. **Steam / Epic / GOG / CDKeys** open the right storefront but **without** Quenly affiliate params where IDs are missing. **Commission accrual: not confirmed** without partner-cabinet data.
