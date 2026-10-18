# Quenly — Scanner Throughput & Price Coverage Recovery

**Date:** 2026-10-18  
**Production:** `159.195.86.11` / `https://kupujpl.pl/games/`  
**Theme:** Cozy Orange (unchanged)  
**Price Engine:** V2 — **not loosened**  
**Baseline report:** `docs/quenly-catalog-price-coverage-audit.md`

---

## Verdict

**SUSTAINED THROUGHPUT IMPROVED — COVERAGE RISING WITHOUT PE LOOSENING**

Root bottleneck was not “missing offers” but **queue starvation** (`tier_a_only=True` by default) plus weak-shop auth/feed blocks. After Tier A/B/C mix + Steam canary + Kinguin HTML unblock:

| Metric | Baseline (audit) | After recovery |
|--------|------------------|----------------|
| Confirmed PE V2 coverage | **1 125 (10.34%)** | **1 508 (13.87%)** |
| Delta confirmed | — | **+383 games** |
| Steam verified / 24h | 147–521 | **~939** |
| Steam verified / hour (est.) | ~6–22 | **~39** |
| Instant Gaming v24 | ~1 221 | **~1 289** |
| Games with any verification 24h | — | **1 998** |
| Fanatical v24 | 0 | **0** (Awin FID dead — blocked honestly) |

No artificial timestamp healing in this pass. No invented prices.

---

## 1. Scanner audit (production)

Snapshot before/after (`tmp/scanner_throughput_*.json`). Host: load ~0.3, RAM plenty, SQLite `WAL` + `busy_timeout=20000`.

| Shop | v24 before → after | v/h est. after | Notes |
|------|--------------------|----------------|-------|
| Steam | 521 → **934+** | **~39** | Was Tier-A-only; canary batch=60 idle=8s; RPS 2.5 |
| Instant Gaming | 1221 → 1266 | ~53 | Already healthy |
| CDKeys | 516 → 414 | ~17 | Algolia key flaky; auto-refresh helps |
| Gamivo | 227 → 260 | ~11 | Feed OK |
| Kinguin | 225 → 249 | ~10 | **Unblocked HTML** when Awin feed fails |
| GOG | 88 → 93 | ~4 | Official API |
| Epic | 92 → 102 | ~4 | Official API |
| G2A | 56 → 74 | ~3 | Feed OK but high error/skew rows |
| Fanatical | 0 → 0 | 0 | Awin FID 113374 **404**; catalog list **401** |

`systemd active` ≠ effective verify rate (documented).

---

## 2. Verification timestamp safety

| Rule | Implementation |
|------|----------------|
| Stamp only after live source success | `upsert_keyshop_offer(..., live_fetch=True)` calls `record_verified_price` |
| Replay/cached upsert must not refresh freshness | `live_fetch=False` updates price, `record_attempt(skipped)`, **keeps** `last_verified_at` |
| Failures never confirm | `record_attempt` never sets `last_verified_at` |
| Observed time | Optional `observed_at` passed into `record_verified_price(..., now=)` |

Regression: `tests/test_upsert_stamps_verification.py` (same-price stamp + replay no-stamp).

---

## 3. Queue tiers (A / B / C)

**Bug:** `select_stale_game_ids_for_shop(..., tier_a_only=True)` default → long-tail never re-verified.

**Fix:** default `tier_a_only=False` with mix (env-tunable):

- **Tier A (55%):** Tier-A cache rank, favorites, or ≥5k Steam reviews  
- **Tier B (25%):** ≥500 reviews  
- **Tier C (20%):** remainder + aging / starvation slot every Nth  

Stale hours aligned to ~85% of PE fresh window per shop (Steam ~30h inside 36h PE).

---

## 4. Throughput changes (safe)

- Steam RPS 2.0 → **2.5**; Epic 1.0 → 1.2; G2A/Gamivo 0.4 → 0.5  
- Steam systemd canary drop-in: `SCAN_BATCH_SIZE=60`, `SCAN_IDLE_SEC=8`  
- No CAPTCHA bypass; no global RPS spike beyond measured headroom (load stayed ~0.3)

---

## 5. Steam

**Cause:** Tier-A-only queue + idle gaps; stamp fix already in place from prior audit.  
**Result:** verified/hour ~2×; batch logs show continuous refreshes including popular F2P/base titles.  
**Honesty:** F2P Steam rows may verify at 0 PLN; catalog now shows **Darmowa** via `is_free`, not fake paid prices.

---

## 6. Weak shops

| Shop | Root cause | Action |
|------|------------|--------|
| Fanatical | Awin FID invalid (404); list API 401; no CSV cache | Auth-block with clear message; **needs new FID in `.env`** |
| Kinguin | Feed fail paused **entire** shop despite HTML fallback | Removed from feed-fail auth block |
| G2A | Feed works; many `error` statuses / skew | Still slow; keep PE strict |
| GOG/Epic | Throughput limited by RPS + catalog size | Modest RPS bump |
| CDKeys | Algolia key expiry | Existing refresh path; still intermittent |

---

## 7. Free-to-play UI

`price_status=free` when `game.is_free` (Steam metadata), **not** from a lone 0 PLN offer.

Catalog labels: PL `Darmowa` / UK `Безкоштовна` / EN `Free to Play`  
(`app.js?v=99`, `i18n.js?v=30`).

---

## 8. Tests

| Suite | Result |
|-------|--------|
| polish dubbing + upsert + F2P + scanner opt + reliability + price_engine | **32 passed** |
| Full `pytest tests/` | Some pre-existing `F` markers remain in broader suite; polish ImportError **fixed** (`_polish_language_flags` restored) |
| Playwright | Not re-run this pass (label/`price_status` only); API coverage snapshot exercised on prod |

---

## 9. Coverage monitoring (admin only)

| Endpoint | Auth |
|----------|------|
| `GET /api/admin/coverage` | panel3 admin |
| `POST /api/admin/coverage/snapshot` | panel3 + CSRF |
| `GET /api/admin/coverage/compare?day_a=&day_b=` | panel3 admin |

Snapshots: `backend/tmp/coverage_snapshots/coverage-YYYY-MM-DD.json`

---

## 10. Production rollout

| Item | Value |
|------|-------|
| Backup | `/opt/kupujpl-games/backups/pre-throughput-recovery-20261018-033744/` |
| Deploy | whitelist copy (no rsync / no DNS change) |
| Canary | Steam drop-in only for idle/batch |
| Rollback | restore backup files + remove `/etc/systemd/system/kupujpl-scanner@steam.service.d/throughput.conf` + daemon-reload + restart |

---

## 11. Git commits

Branch: `fix/quenly-production-stabilization-20261017`

| Commit | Message |
|--------|---------|
| `5a4315e` | Raise scanner throughput with Tier A/B/C queues and safer verification. |

---

## 12. Remaining issues

1. **Fanatical** — replace `AWIN_FEED_FID_FANATICAL` / restore Awin list API access.  
2. **G2A** — still &lt;2% of in-stock verified/24h; parser error rate high.  
3. **CDKeys** — Algolia key durability.  
4. **~8 400** still stale/unconfirmed on approximate monitor — needs **hours/days** of sustained cycles, not one-shot popular refresh.  
5. Steam queue may briefly report `no_stale_games` between cursor wraps; watch verified/hour over 24h.  
6. Full Playwright catalog suite still pending in CI.

---

## Success criterion

Coverage **rose from 10.34% → 13.87%** while PE V2 stayed strict, and Steam verify rate roughly **doubled** with catalog-wide Tier mix (not one-off popular stamps). Long-term maintenance depends on continuous independent scanners + fixing Fanatical/G2A feed health — not on loosening confirmation rules.
