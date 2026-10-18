# Quenly — Steam Currency & Price Accuracy Final Report

**Date:** 2026-10-18  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange — unchanged  
**Price Engine:** V2 — thresholds unchanged  
**Prior:** `docs/quenly-72h-price-coverage-stability.md` (`5854645`)  
**Status:** **DEFECT FIXED — MONITORING**

---

## 1. Rogue Trader 14.99 PLN verdict

**Not a USD-stored-as-PLN bug on the base game.**

| Fact | Value |
|---|---|
| Suspected display | Steam **14.99** on short slug `warhammer-40000-rogue-trader` |
| Actual product resolved (pre-fix) | **Voidfarer Pack** (Steam AppID **2682670**), not the base game |
| Base game DB offer | Game ID **1602**, Offer ID **550**, Steam AppID **2186680**, **199.99 PLN** |
| Live Steam `cc=pl` for 2186680 | `currency=PLN`, `final=19999` → **199,99 zł** |
| Live Steam `cc=us` for 2186680 | `currency=USD`, `final=4999` → **$49.99** (not $14.99 at audit time) |

**Root cause of the 14.99 display:** short-slug resolution (`resolve_game_slug`) picked the **highest Steam appid** among `warhammer-40000-rogue-trader-%` extensions. DLC/packs often have higher appids than the base game, so **Voidfarer Pack (14.99 PLN)** won over **Rogue Trader (199.99 PLN)**.

Post-fix API check:

```text
title Warhammer 40,000: Rogue Trader
appid 2186680
best Steam 199.99 confirmed
```

---

## 2. Original source price and currency (base game)

Steam Store API `appdetails?appids=2186680&cc=pl`:

- `price_overview.currency` = **PLN**
- `price_overview.final` = **19999** (minor units)
- `price_overview.final_formatted` = **199,99 zł**
- Package list includes **782856**
- Product `type` = **game**

Stored offer 550 matches this PLN source (199.99). Provenance: `price_source=steam`, `last_verified_at=2026-10-18 03:29:19`, `last_check_status=verified`.

---

## 3. Steam PL price evidence

| Region param | Currency | Final (minor) | Formatted |
|---|---|---:|---|
| `cc=pl` | PLN | 19999 | 199,99 zł |
| `cc=us` | USD | 4999 | $49.99 |
| `cc=de` | EUR | 4999 | 49,99€ |

Language `l=polish` is **not** used as a currency guarantee; `cc=pl` + `currency` field are authoritative.

---

## 4. Relevant Steam App ID / package

| Product | AppID | Role |
|---|---:|---|
| Warhammer 40,000: Rogue Trader | **2186680** | Base game (correct) |
| Voidfarer Pack | 2682670 | Cosmetic pack (was wrongly selected by short slug) |
| Steam package (base) | 782856 | From appdetails `packages` |

---

## 5. Exact root causes

### A. Slug family resolution (confirmed — caused 14.99 display)

`_pick_best_game()` keyed on `steam_appid` ascending preference for **higher** IDs → DLC/packs beat the base game.

**Fix:** prefer non-DLC heuristics + `steam_review_count` / recommendations; **remove** higher-appid preference.

### B. Steam parser ignored `price_overview.currency` (latent — hardened)

`_upsert_steam_offer` did `final/100` and labeled the result PLN without reading `currency`. With `fetch_appdetails(..., cc="pl")` this usually returns PLN, and the 100-offer live audit found **0** USD-as-PLN mismatches — but the code was unsafe if Steam ever returned USD/EUR under a PL request (geo/proxy) or if `cc` were wrong.

**Fix:** `_steam_price_overview_to_pln()` requires explicit currency; converts via existing NBP `money_to_pln`; refuses missing/unknown currency (records `error` attempt, keeps prior verified price).

---

## 6. Steam offers audited

| Scope | Result |
|---|---|
| Popular verified Steam offers (reviews ≥ 500, n=100) | **90** matched live `cc=pl` PLN within 0.05 |
| API errors (429) | 10 |
| Price mismatches vs live PLN | **0** |
| USD-as-PLN suspects (stored == US major units ≠ PL) | **0** |
| `cc=pl` response not PLN | **0** |

Artifact: `/opt/kupujpl-games/backend/tmp/steam_currency_audit.json`

---

## 7. Currency errors found

| Class | Count |
|---|---:|
| Confirmed foreign amount stored as PLN (sample) | **0** |
| Wrong-product short-slug displays (Rogue Trader family) | **1 pattern** (fixed) |
| Parser latent (no currency gate) | **1** (hardened) |

---

## 8. Cross-shop currency findings

| Shop | Handling |
|---|---|
| Steam | Now requires `currency` + FX/`PLN`; fetch uses `cc=pl` |
| GOG | Already requires `currency.code == PLN` |
| Epic | Already requires `currencyCode == PLN` |
| Instant Gaming | Explicit PLN page / EUR→`to_pln` |
| Keyshops (Kinguin/G2A/Gamivo/…) | `currency_pln.money_to_pln` / unit detection |

No additional foreign-as-PLN defect confirmed in this pass beyond Steam’s missing currency gate.

---

## 9. Impact on current prices

- Base Rogue Trader catalog/API for the **canonical** slug was already **199.99 PLN**.
- Short slug `/games/api/games/warhammer-40000-rogue-trader` previously showed Voidfarer **14.99** (wrong product). **Fixed** → base **199.99**.
- No mass Steam price rewrite performed (audit found no USD-as-PLN cohort).

---

## 10. Impact on historical prices

- Base game offer 550 history remains tied to PLN verifies (~199.99).
- Voidfarer Pack history at 14.99 is a **separate game_id** — not silently deleted.
- Dry-run: no bulk historical purge authorized; wrong short-slug traffic would have attributed pack prices to the short URL, not polluted the base game’s `lowest_ever` row.

---

## 11. Corrections applied

1. `backend/app/core/slug_lookup.py` — base-game preference for short-slug families  
2. `backend/app/parsers/steam_catalog.py` — currency-aware PLN conversion  
3. Tests: `test_slug_lookup_base_game.py`, `test_steam_currency_pln.py`  
4. Production whitelist deploy (minimal)

No mass DB updates. No PE threshold loosening. No RPS increase. No Cozy Orange changes.

---

## 12. Full pytest results

| Suite | Result |
|---|---|
| Slug + Steam currency + Playwright | **12 passed** |
| Full `tests/` (junit after service recovery) | **233 passed, 0 failed** (transient 502s during restart caused an earlier Playwright flake) |

---

## 13. Playwright results

**5/5 passed** when production returned HTTP 200 (post-restart). Earlier failures were **502 Bad Gateway** during `systemctl restart`, not assertion weakenings.

---

## 14. Git commits

| Commit | Topic |
|---|---|
| *(this pass)* | Slug base-game preference + Steam currency gate + report |

---

## 15. Production whitelist

**Backup:** `/opt/kupujpl-games/backups/pre-steam-currency-20261018-070327`

| File | SHA256 (deployed) |
|---|---|
| `slug_lookup.py` | `d2292dcac9e0ad71989715362486b5ae6a6dc729a61887e68bf3ea20ae9bc9fe` |
| `steam_catalog.py` | `b9adf1982b834b605533f5b5cc820b61a22c91021372f2eba02516faf8c95db9` |

---

## 16. Backup and rollback

```bash
BK=/opt/kupujpl-games/backups/pre-steam-currency-20261018-070327
cp -a "$BK/backend__app__core__slug_lookup.py" /opt/kupujpl-games/backend/app/core/slug_lookup.py
cp -a "$BK/backend__app__parsers__steam_catalog.py" /opt/kupujpl-games/backend/app/parsers/steam_catalog.py
systemctl restart kupujpl-games.service
```

---

## 17. Remaining risks

1. Short-slug families for other franchises — monitor via similar prefix resolution; DLC heuristic is best-effort.  
2. Steam 429 during audits — keep rate-limited refreshes.  
3. Offer rows still do not persist source currency metadata — PE cannot re-audit currency without a live fetch; consider a future optional column (out of scope).  
4. Re-run a larger Steam live sample after rate limits cool for ongoing monitoring.

---

## Final status

### **DEFECT FIXED — MONITORING**

The alarming **14.99 PLN Rogue Trader** finding was a **wrong-product short-slug** selection (Voidfarer Pack), not USD mislabeled as PLN on the base game. Base Steam PLN **199.99** is source-verified. Steam currency handling is now explicit; a 100-offer live sample found **0** foreign-as-PLN stores. Continue monitoring — do not claim blanket `CURRENCY ACCURACY VERIFIED` for the entire catalog without broader longitudinal checks.
