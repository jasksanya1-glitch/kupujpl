# Quenly — Parallel Scanner Performance Final Report

**Date:** 2026-10-18 (UTC)  
**Host:** `159.195.86.11` / `/opt/kupujpl-games`  
**Site:** https://kupujpl.pl/games/  
**Theme:** Cozy Orange — unchanged  
**Price Engine:** V2 — unchanged (no threshold loosening)  
**Status:** **VERIFIED IMPROVEMENT — LONG-TERM PENDING**

Sustained improvement requires 48–72h of hourly coverage snapshots. Do not treat the short canary as long-term proof.

---

## 1. Exact bottlenecks identified

| Bottleneck | Evidence | Impact |
|---|---|---|
| Serial per-game loop inside each shop process | `scan_shop_batch` processed one game at a time despite `budget.concurrency` | HTTP latency not overlapped within RPS budget |
| GOG/Epic one-shot `requests.get/post` | No keep-alive | Extra TCP/TLS cost per call |
| Steam idle/batch (already partially fixed) | Override was batch=60 idle=8 | Under-utilized RPS between batches |
| Fanatical Awin FID invalid | `shop_auth_blocker` → `auth_failed` | 0 verifications; correctly idle |
| CDKeys Algolia key missing/expired | Auth blocker / queue message | Intermittent zero batches |
| Tier C backlog | Large unpaid catalog | Coverage growth depends on Tier C scan share (already fair-mixed) |
| GOG/Epic low hit rate | Many batches `last_batch_verified=0` while still calling APIs | Matching / stock / offer stamp — not RPS |

Not bottlenecks (this pass): CPU/RAM (load ~0.5–0.9, ~2.3 GiB used / 16 GiB), Steam RPS ceiling (left at 2.5).

---

## 2. Optimizations implemented

1. **Bounded parallel game processing** inside `scan_shop_batch` via `ThreadPoolExecutor(max_workers=budget.concurrency)` with a **shared** `_RateLimiter` (RPS not multiplied).
2. **In-flight game-id set** per shop — no concurrent duplicate scan of the same game/shop.
3. **HTTP session pool** (`http_pool.py`) for GOG + Epic — thread-local `requests.Session` keep-alive.
4. **GOG/Epic concurrency** raised 2→3 **without** raising RPS (1.5 / 1.2).
5. **Steam canary** systemd override: `SCAN_BATCH_SIZE=80`, `SCAN_IDLE_SEC=5` (RPS unchanged at 2.5).
6. Progress JSON records `workers` + `rps_budget` for observability.
7. Tests: `tests/test_scan_parallel_safety.py` (RPS floor, inflight dedupe, budget ceilings).

**Not done (by design):** RPS hikes, CAPTCHA bypass, Fanatical credential fabrication, schema rewrite, asyncio rewrite, multi-writer farm.

---

## 3. Per-shop throughput before / after

### Verified offers — 1h window (pre-deploy snapshot vs extrapolated post)

| Shop | Pre `verified_1h` (deploy start) | Post `verified_15m` ×4 (canary) | Notes |
|---|---:|---:|---|
| Steam | 2280 | ~2340 (585×4) | Stable; best batch 63/76 in 30.3 s @ workers=3 |
| GOG | 38 | ~140 (35×4) | Workers=3 live; hit-rate still low |
| Epic Games | 46 | ~152 (38×4) | Same pattern as GOG |
| G2A | 39 | ~144 | Feed+HTML; workers=1 |
| Kinguin | 34 | ~124 | workers=2 |
| CDKeys | 116 | ~160 | Auth flapping |
| Gamivo | 43 | ~144 | |
| Instant Gaming | 166 | ~0 (15 m) | Transient; investigate separately |
| Fanatical | 0 | 0 | Auth-idle (expected) |

### Steam batch wall-clock (illustrative)

| Moment | size | verified | sec | workers | vph_est |
|---|---:|---:|---:|---:|---:|
| Pre (stability era) | 60 | 51 | 23.9 | — | high |
| Post outlier | 78 | 28 | 209 | 3 | 481 |
| Post healthy | 76 | 63 | 30.3 | 3 | **7488** |

Use multi-batch / hourly metrics, not single-batch spikes.

---

## 4. Unique games verified / hour

Steam remains the primary unique-game engine (~2.2–2.3k verified stamps / hour in the measured windows). Cross-shop unique paid-game growth shows up as **confirmed coverage**, not as a single shop counter.

---

## 5. HTTP requests vs successful verification

- Rate limiters still gate **one wait per game** (≈ one primary request path per game for official shops).
- Parallelism only overlaps wait/latency; it does **not** increase permitted RPS.
- Steam healthy batch: 76 attempts → 63 verified (~83% success).
- GOG/Epic: attempts continue with near-zero `last_batch_verified` — requests happen; verification stamps do not (matching/stock), so efficiency per request remains the open issue for those shops.

---

## 6. CPU / RAM / SQLite before / after

| Metric | Baseline (phase 1) | Post canary |
|---|---|---|
| Load avg | 0.54 / 0.44 / 0.39 | 0.53–0.80 / ~0.5–0.6 / ~0.46 |
| RAM used | ~2.1 GiB | ~2.3 GiB |
| RAM available | ~13 GiB | ~13.7 GiB |
| SQLite | WAL + `busy_timeout` | Unchanged schema; concurrent short sessions per worker |

No SQLite outage observed during canary. Contention remains a watch item under 9 scanners.

---

## 7. Tier A / B / C classification

Classifier unchanged this pass (`TIER_A_CACHE_TOP_N=1000` from stability fix).

| Tier | Games | Confirmed (post) | % |
|---|---:|---:|---:|
| A | 1726 | 1652 | 95.71 |
| B | 1183 | 1140 | 96.37 |
| C | 7505 | 1007 | 13.42 |

Tier B is healthy (not the prior empty-band bug). Tier C is receiving scan time and driving coverage gains.

---

## 8. Confirmed price coverage before / after

| Snapshot | Paid games | Confirmed | % |
|---|---:|---:|---:|
| Earlier today (stability report) | 10414 | 3142 | 30.17 |
| Deploy pre-baseline | 10414 | 3463 | 33.25 |
| ~10 min post canary | 10414 | 3799 | **36.48** |

Coverage was already rising from prior queue/idle fixes; parallel deploy continued the climb. Claim long-term only after 48–72 h of `kupujpl-coverage-snapshot.timer` data.

---

## 9. Error rates and rate-limit events

- Fanatical: permanent `auth_failed` / long `SCAN_AUTH_IDLE_SEC` — no request storm.
- CDKeys: Algolia key missing/expired messages — no bypass.
- G2A: still produces verifications (no 403 storm observed in this canary window).
- Steam: no elevated 429 signature in the healthy post batch.
- Site smoke: `GET /games/gra/hades-ii` → **200**.

---

## 10. Full pytest

Local Windows run of the full suite was interrupted by environment `KeyboardInterrupt` after **205 passed, 5 skipped** (no failures observed before interrupt).

Critical regression subset (PE V2 + queues + parallel + store_class + tiers + out-of-order): **passed** in focused runs (`test_price_engine`, `test_scan_parallel_safety`, `test_tier_classification`, `test_store_classification_consistency`, plus reliability/parity modules).

`store_class` on `OfferResponse` — **resolved** (field present; schema test passes).

---

## 11. V2 regression results

- `PRICE_ENGINE_V2=1` price-engine tests: passed in focused run.
- No PE threshold changes deployed.
- Failed/auth/cache paths do not stamp success (pre-existing guards retained).
- Out-of-order verification tests included in critical set.

---

## 12. Playwright / SSR smoke

- Production SSR: Hades II **HTTP 200**.
- Catalog API probe with bare `?limit=2` returned 422 (validation) — not introduced by this whitelist; use established catalog query shapes for parity scripts.
- Playwright full suite: not re-run end-to-end in this window; prior stability suite remains the reference. Re-run on next CI pass.

---

## 13. Git commits

Local branch `fix/quenly-production-stabilization-20261017` (prior):

- `6064df3` Fix empty Tier B…
- `d524631` Record stability-verification…

This performance pass: commit created after report (`parallel scanner within-budget workers + HTTP pool`) — see `git log -1` on the branch after commit.

---

## 14. Production whitelist

Deployed only:

| File | Role |
|---|---|
| `backend/app/parsers/shop_scan_queue.py` | Parallel batch + inflight + budgets |
| `backend/app/parsers/http_pool.py` | New Session pool |
| `backend/app/parsers/gog_parser.py` | Session reuse |
| `backend/app/parsers/epic_parser.py` | Session reuse |
| `/etc/systemd/system/kupujpl-scanner@steam.service.d/throughput.conf` | batch=80 idle=5 |

Staging: `/tmp/quenly-parallel-perf-wl/`  
Script: `tmp/deploy_parallel_perf_wl.sh`

---

## 15. Backup and rollback

**Backup:** `/opt/kupujpl-games/backups/pre-parallel-perf-20261018-044651/`

Contains: whitelist file copies, `database.db` online backup, `WHITELIST_MANIFEST.txt` (SHA256 old/new), `baseline_pre.json.txt`, `steam_throughput.conf`, `baseline_post_manual.txt`.

**Rollback (targeted):**

```bash
BK=/opt/kupujpl-games/backups/pre-parallel-perf-20261018-044651
cp -a $BK/backend__app__parsers__shop_scan_queue.py /opt/kupujpl-games/backend/app/parsers/shop_scan_queue.py
cp -a $BK/backend__app__parsers__gog_parser.py /opt/kupujpl-games/backend/app/parsers/gog_parser.py
cp -a $BK/backend__app__parsers__epic_parser.py /opt/kupujpl-games/backend/app/parsers/epic_parser.py
rm -f /opt/kupujpl-games/backend/app/parsers/http_pool.py   # was MISSING pre-deploy
cp -a $BK/steam_throughput.conf /etc/systemd/system/kupujpl-scanner@steam.service.d/throughput.conf
systemctl daemon-reload
systemctl restart kupujpl-games.service
for s in steam gog epic instantgaming kinguin g2a gamivo cdkeys fanatical; do
  systemctl restart kupujpl-scanner@$s.service
done
```

Forbidden actions were not used (no full rsync, no `--delete`, no `git reset --hard`, no mass DB healing, no PE loosen, no Cozy Orange redesign).

---

## 16. Remaining bottlenecks

1. **GOG / Epic verification hit-rate** — parallel + keep-alive help latency; matching/stock still yields many zero-verify batches.
2. **Fanatical** — needs a valid Awin feed. Configure `AWIN_FEED_FID_FANATICAL` (and ensure merchant id `118821` / program membership is correct). Do not invent credentials. Until then, auth-idle is correct.
3. **CDKeys Algolia token** — refresh authorized key; circuit already present.
4. **Instant Gaming** — 15 m zero verify in canary; check HTML/API path separately.
5. **Tier C absolute volume** — still ~86% unconfirmed; needs sustained hours, not RPS spikes.
6. **SQLite write contention** — watch under parallel workers; introduce a single writer queue only if busy/locked events rise.

---

## 17. Sustainability status

**VERIFIED IMPROVEMENT — LONG-TERM PENDING.**

Evidence of real improvement in this window:

- Parallel workers active (`workers=3` on Steam/GOG/Epic).
- Steam healthy batch ~63 verified / 30 s with unchanged RPS.
- Paid confirmed coverage **30.17% → 36.48%** across the morning (mixed prior fixes + this canary).
- Tier C confirmed **402 → 1007**.
- Load/RAM still comfortable.

Leave `kupujpl-coverage-snapshot.timer` enabled. Re-evaluate after 48–72 h; promote to **SUSTAINED IMPROVEMENT** only if coverage and verified/hour stay up without error-rate growth.

---

## Fanatical — authorized restore checklist

1. Confirm Awin publisher membership for **Fanatical Global** (merchant id currently coded as `118821`).
2. Obtain a valid feed download FID from Awin (product feed CSV).
3. Set `AWIN_FEED_FID_FANATICAL=<fid>` in `/opt/kupujpl-games/backend/.env` (or drop a valid CSV into the feed cache path used by `affiliate_feeds._cache_path("Fanatical")`).
4. Restart `kupujpl-scanner@fanatical.service`.
5. Confirm `shop_auth_blocker("Fanatical")` returns `None` and queue phase leaves `auth_failed`.

---

*Generated as part of Quenly maximum safe scanner performance optimization — 2026-10-18.*
