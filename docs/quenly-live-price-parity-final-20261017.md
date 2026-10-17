# Quenly live price parity — final report (2026-10-17)

**STATUS: STABLE WITH ISSUES**

Critical price parity and SEO branding are fixed on production. Desktop CLS remains above target. Bare `curl` User-Agents receive HTTP 403 (not 500).

---

## 1. Root cause — wrong prices on `/promocje`

Production `seo_landings.py` used a **private `_best_offers_map`** that picked the raw cheapest in-stock `Offer.price_pln` with **no Price Engine V2 / matching filters**.

Meanwhile `/gra/{slug}` and `/api/games/{slug}` already used `best_offers_map` → `best_offers_map_v2` (confirmed only).

So Rogue Trader showed:

| Surface | Before | After |
|---------|--------|-------|
| `/promocje` | **8.99 PLN GOG** (Dawn of War wrong SKU) | **absent** (no savings vs Steam/Epic 199.99) |
| `/gra/...rogue-trader...` | 199.99 Epic | 199.99 Epic |
| `/api/games/...` | 199.99 Epic | 199.99 Epic |

GOG URL: `gog.com/.../warhammer_40000_dawn_of_war_anniversary_edition` — PE V2 tier **rejected** (`edition_mismatch`).

Local workspace already had the PE V2 wiring; **production was still on the legacy local min() helper** (dirty tree / incomplete earlier deploy).

---

## 2. Pages fixed (branding + PE path)

All SEO collection landings that call `collect_landing_items`:

- `/promocje`
- `/najwieksze-okazje`
- `/gry-pc-do-{10,20,30,50,100}-zl`
- `/gry-pc-znizka-{50,70,80,90}`
- `/gry-rpg`, `/gry-strategie`, `/gry-co-op`
- `/najtansze-gry-steam`, `/gry-steam-tanio`
- category landings via shared skin
- `/darmowe-gry` (skin/branding)

Now use `best_offers_map` / `steam_offers_map` from `game_offer_selection` (PE V2 when `PRICE_ENGINE_V2=1`).

---

## 3–4. SSR “HTTP 500” investigation

**No production traceback / no real HTTP 500** for the reported game URLs.

| Client | Result |
|--------|--------|
| Browser Chrome UA | **200** |
| Googlebot UA | **200** |
| `curl/8.0` UA | **403** (WAF / bot filter, body ~7 bytes) |
| `http://127.0.0.1:8000/...` | **200** |

Independent tools that use a curl-like UA can mis-report **403 as failure**; that must not be documented as HTTP 500. Googlebot is unaffected.

Regression: `tests/test_ssr_bot_status.py`.

---

## 5–6. Test results

| Profile | Command | Result |
|---------|---------|--------|
| Legacy default (`PRICE_ENGINE_V2` unset → `0` via `setdefault`) | promocje + seo + PE + edition + matching + unverified | **28 passed** |
| V2 profile (`PRICE_ENGINE_V2=1`) | `test_price_engine` + `test_promocje_price_parity_v2` | **14 passed** |

`conftest.py` now uses `os.environ.setdefault("PRICE_ENGINE_V2", "0")` so an explicit V2 profile is not overwritten.

New tests:

- `tests/test_promocje_price_parity_v2.py` — Rogue Trader Dawn of War rejected; landings call canonical `best_offers_map`
- `tests/test_ssr_bot_status.py` — live browser/Googlebot 200; curl ≠ 500

---

## 7–8. Price parity before / after (evidence)

**Before (live `/promocje` cards):**

- Rogue Trader **8.99** GOG −96%
- Hades II **28.63** Gamivo
- Guacamelee **2.29** Gamivo
- Civilization VI **20.65** Kinguin

**After (live verify 2026-10-17):**

- Rogue Trader **not on `/promocje`**; API/SSR **199.99 Epic**; no `8.99` on promocje HTML
- Guacamelee promocje **4.80** (aligned with quality path; API **4.8 Kinguin**)
- Hades II API **117.0 Epic**
- Civilization VI API **188.04 Instant Gaming**
- `/promocje` title: `… | Quenly.pl`; KupujPL count **0**; Quenly logo present

---

## 9. Cozy Orange consistency

`/promocje` and other SEO skins now use:

- Quenly logo (`quenly-logo-w400.webp/png?v=5`)
- `theme-cozy-orange-app.css?v=23`
- Titles / breadcrumbs / FAQ copy → **Quenly.pl** (user-visible KupujPL stripped from collection pages)

Composition of Cozy Orange home unchanged.

---

## 10–11. Lighthouse (honest)

**Before (prior report):** mobile perf ~83 / LCP ~3.6s; desktop perf ~86 / CLS **0.206**.

**After (this pass, 3 runs):**

| Form | Run | Perf | CLS | LCP (ms) |
|------|-----|------|-----|----------|
| Mobile | 1 | 81 | 0.068 | 3746 |
| Mobile | 2 | 73 | 0.152 | 4212 |
| Mobile | 3 | 77 | 0.000 | 4418 |
| Desktop | 1 | 85 | 0.217 | 1083 |
| Desktop | 2 | 74 | 0.591 | 1100 |
| Desktop | 3 | 73 | 0.591 | 1092 |

**Desktop CLS median ≈ 0.59 — target &lt; 0.1 not met.** Logo intrinsic size aligned with CSS; catalog empty min-height softened. Remaining CLS likely catalog/news hydration — tracked as open issue.

Artifacts: `docs/lh-parity-20261017/`.

---

## 12. Git

Local branch: `fix/quenly-production-stabilization-20261017`  
Prior release tip: `cbac0ee` / report hash `bc63279`  
This work: commit on the same branch (price-parity + SEO Quenly + tests).

Production checkout remains dirty (`fix/technical-seo-indexing` + hotfixes); **whitelist file deploy only** — no full rsync / reset.

---

## 13. Deployed whitelist

```
backend/app/core/seo_landings.py
backend/app/core/seo_pages.py
backend/app/core/game_page_html.py
backend/app/static/theme-cozy-orange-app.css
backend/app/static/index.html
backend/app/static/{redakcja,regulamin,polityka-prywatnosci,o-nas,kontakt}.html
```

Service: `systemctl restart kupujpl-games` → **active**.

---

## 14. Backup

`/opt/kupujpl-games/backups/live-parity-20261017T2039Z/`

- `seo_landings.py` (md5 `3784eef8187a39416d8e9259990dac4d`)
- `seo_pages.py` (md5 `1b39aae30e49fa026585b8e497ac0d27`)

---

## 15. Rollback

```bash
sudo cp /opt/kupujpl-games/backups/live-parity-20261017T2039Z/seo_landings.py \
        /opt/kupujpl-games/backend/app/core/seo_landings.py
sudo cp /opt/kupujpl-games/backups/live-parity-20261017T2039Z/seo_pages.py \
        /opt/kupujpl-games/backend/app/core/seo_pages.py
sudo systemctl restart kupujpl-games
```

(Optionally restore static CSS/HTML from git `HEAD` / prior backup if needed.)

---

## 16. Remaining issues

1. **Desktop CLS** still &gt; 0.1 (median high variance under Lighthouse).
2. Mobile LCP still ~3.7–4.4s (stretch ≤2.5s not met).
3. Production git working tree still dirty / not on stabilization branch tip — operational risk for future deploys.
4. Some FAQ/news strings may still mention historical “KupujPL” in rarely hit templates — collection landings cleaned.
5. Affiliate gaps (GOG/CDKeys refs) unchanged from prior audit.

---

## 17. Exact production verification evidence

```
promocje 200 Quenly 6 KupujPL 0
title Promocje na gry PC — porównanie cen | Quenly.pl
rogue on promocje []
8.99 on page False
/gra/warhammer-40000-rogue-trader-2186680 200 False True   # no 8.99, has 199.99
api rogue-trader 199.99 Epic Games
api hades-ii 117.0 Epic Games
api guacamelee 4.8 Kinguin
api civilization-vi 188.04 Instant Gaming
curl UA hades 403
```

**Not FULLY VERIFIED** because desktop CLS target missed and LCP stretch goal missed — but **critical wrong-SKU pricing and fake-500 curl confusion are resolved**.
