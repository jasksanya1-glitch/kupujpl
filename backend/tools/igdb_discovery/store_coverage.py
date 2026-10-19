"""Store coverage from local caches only — no live shop/scanner requests.

Sources (read-only):
  - tmp/affiliate_feeds/*.csv (G2A, Gamivo, Kinguin, CDKeys, Fanatical)
  - local catalog offers in database.db (joined via games.steam_appid / title)

UNKNOWN means no local evidence — never treat as "no offers exist".
Prices from feeds/offers are historical snapshots, not live quotes.
"""
from __future__ import annotations

import csv
import logging
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from . import config
from .matching import normalize_title

logger = logging.getLogger("igdb_discovery.store_coverage")

FEED_SHOPS = ("G2A", "Gamivo", "Kinguin", "CDKeys", "Fanatical")
FEEDS_DIR = config.BACKEND_DIR / "tmp" / "affiliate_feeds"

_EDITION_HINTS = (
    "deluxe",
    "ultimate",
    "complete",
    "goty",
    "gold",
    "premium",
    "standard",
    "legendary",
    " Remastered",
    "remaster",
    "remake",
    "game of the year",
)
_PLATFORM_HINTS = (
    ("pc", ("pc", "steam", "windows")),
    ("ps", ("ps4", "ps5", "playstation", "psn")),
    ("xbox", ("xbox", "series x", "series s", "xbox one")),
    ("switch", ("nintendo", "switch")),
)
_REGION_HINTS = (
    ("EU", ("eu", "europe", "emea")),
    ("PL", (" poland", " pl ", "polish")),
    ("GLOBAL", ("global", "ww", "worldwide", "row")),
    ("US", (" usa", " us ", "north america", "na ")),
    ("UK", (" uk ", "united kingdom", "britain")),
)


@dataclass
class StoreHit:
    shop: str
    source: str  # affiliate_feed | local_offers
    product_name: str | None
    edition: str | None
    region: str | None
    platform: str | None
    match_confidence: float
    product_match: str  # exact | likely | weak | unknown
    price_pln: float | None = None
    price_freshness: str = "historical_snapshot_not_live"
    url: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StoreCoverageResult:
    igdb_id: int
    name: str
    steam_appid: int | None
    status: str  # known_offer | unknown | partial
    hits: list[StoreHit] = field(default_factory=list)
    shops_with_hits: list[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "igdb_id": self.igdb_id,
            "name": self.name,
            "steam_appid": self.steam_appid,
            "status": self.status,
            "hits": [h.to_dict() for h in self.hits],
            "shops_with_hits": self.shops_with_hits,
            "summary": self.summary,
            "note": (
                "UNKNOWN means no local evidence found; "
                "it does not prove shops lack this title. "
                "Prices are historical snapshots, not live."
            ),
        }


def _guess_edition(title: str) -> str | None:
    n = (title or "").lower()
    for h in _EDITION_HINTS:
        if h.lower().strip() in n:
            return h.strip().title()
    return "unknown"


def _guess_platform(title: str) -> str | None:
    n = f" {(title or '').lower()} "
    for plat, keys in _PLATFORM_HINTS:
        if any(k in n for k in keys):
            return plat
    return "unknown"


def _guess_region(title: str) -> str | None:
    n = f" {(title or '').lower()} "
    for reg, keys in _REGION_HINTS:
        if any(k in n for k in keys):
            return reg
    return "unknown"


def _token_overlap(a: str, b: str) -> float:
    ta = {t for t in normalize_title(a).split() if len(t) > 1}
    tb = {t for t in normalize_title(b).split() if len(t) > 1}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), len(tb))


def _feed_path(shop: str) -> Path:
    return FEEDS_DIR / f"{shop.lower()}.csv"


class LocalStoreIndex:
    """In-memory index over local feed CSVs + catalog offers. No network."""

    def __init__(
        self,
        *,
        catalog_db: Path | None = None,
        feeds_dir: Path | None = None,
    ) -> None:
        self.catalog_db = catalog_db or config.CATALOG_DB
        self.feeds_dir = feeds_dir or FEEDS_DIR
        self._feed_rows: dict[str, list[dict[str, str]]] = {}
        self._feed_by_norm: dict[str, dict[str, list[dict[str, str]]]] = {}
        self._feed_by_token: dict[str, dict[str, list[dict[str, str]]]] = {}
        self._offers_by_steam: dict[int, list[dict[str, Any]]] = {}
        self._offers_by_title: dict[str, list[dict[str, Any]]] = {}
        self._meta: dict[str, Any] = {}
        self._loaded = False

    def load(self) -> dict[str, Any]:
        if self._loaded:
            return self._meta
        feed_counts: dict[str, int] = {}
        for shop in FEED_SHOPS:
            path = self.feeds_dir / f"{shop.lower()}.csv"
            rows: list[dict[str, str]] = []
            if path.is_file() and path.stat().st_size > 0:
                with path.open(encoding="utf-8", errors="replace", newline="") as fh:
                    reader = csv.DictReader(fh)
                    for raw in reader:
                        name = (raw.get("product_name") or "").strip()
                        if not name:
                            continue
                        rows.append(
                            {
                                "product_name": name,
                                "url": (raw.get("url") or "").strip(),
                                "price": (raw.get("price") or "").strip(),
                                "currency": (raw.get("currency") or "").strip(),
                                "availability": (raw.get("availability") or "").strip(),
                            }
                        )
            self._feed_rows[shop] = rows
            by_norm: dict[str, list[dict[str, str]]] = {}
            by_token: dict[str, list[dict[str, str]]] = {}
            for r in rows:
                key = normalize_title(r["product_name"])
                if not key:
                    continue
                # Index full title + first 4 tokens for fuzzy prefix lookup.
                by_norm.setdefault(key, []).append(r)
                toks = key.split()
                if len(toks) >= 2:
                    by_norm.setdefault(" ".join(toks[: min(4, len(toks))]), []).append(r)
                # First significant token → shortlist (no full CSV scan per candidate).
                for tok in toks[:3]:
                    if len(tok) >= 4:
                        bucket = by_token.setdefault(tok, [])
                        if len(bucket) < 80:
                            bucket.append(r)
            self._feed_by_norm[shop] = by_norm
            self._feed_by_token[shop] = by_token
            feed_counts[shop] = len(rows)

        offer_count = 0
        if self.catalog_db.is_file():
            con = sqlite3.connect(self.catalog_db)
            con.row_factory = sqlite3.Row
            try:
                tables = {
                    r[0]
                    for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                if "offers" in tables and "games" in tables:
                    q = """
                    SELECT o.shop_name, o.price_pln, o.activation_region, o.in_stock,
                           o.updated_at, o.match_confidence, o.affiliate_url,
                           g.title, g.steam_appid, g.platform
                    FROM offers o
                    JOIN games g ON g.id = o.game_id
                    """
                    for row in con.execute(q):
                        offer_count += 1
                        d = dict(row)
                        sid = d.get("steam_appid")
                        if sid is not None:
                            self._offers_by_steam.setdefault(int(sid), []).append(d)
                        nt = normalize_title(d.get("title") or "")
                        if nt:
                            self._offers_by_title.setdefault(nt, []).append(d)
            except sqlite3.Error as exc:
                logger.warning("local offers index skipped: %s", exc)
            finally:
                con.close()

        self._meta = {
            "feeds_dir": str(self.feeds_dir),
            "feed_row_counts": feed_counts,
            "local_offers_count": offer_count,
            "catalog_db": str(self.catalog_db),
            "live_requests": 0,
            "scanners_started": False,
        }
        self._loaded = True
        return self._meta

    def lookup(
        self,
        *,
        igdb_id: int,
        name: str,
        steam_appid: int | None,
    ) -> StoreCoverageResult:
        self.load()
        hits: list[StoreHit] = []

        # 1) Local offers by Steam AppID (strongest when candidate already linked).
        if steam_appid:
            for o in self._offers_by_steam.get(int(steam_appid), []):
                hits.append(
                    StoreHit(
                        shop=str(o.get("shop_name") or "?"),
                        source="local_offers",
                        product_name=o.get("title"),
                        edition=_guess_edition(o.get("title") or ""),
                        region=o.get("activation_region") or "unknown",
                        platform=o.get("platform") or "unknown",
                        match_confidence=float(o.get("match_confidence") or 0.95),
                        product_match="exact",
                        price_pln=float(o["price_pln"]) if o.get("price_pln") is not None else None,
                        price_freshness="historical_offer_row_not_live",
                        url=o.get("affiliate_url"),
                        note=f"updated_at={o.get('updated_at')}",
                    )
                )

        # 2) Local offers by exact normalized title.
        nt = normalize_title(name)
        for o in self._offers_by_title.get(nt, []):
            if steam_appid and o.get("steam_appid") == steam_appid:
                continue  # already added
            hits.append(
                StoreHit(
                    shop=str(o.get("shop_name") or "?"),
                    source="local_offers",
                    product_name=o.get("title"),
                    edition=_guess_edition(o.get("title") or ""),
                    region=o.get("activation_region") or "unknown",
                    platform=o.get("platform") or "unknown",
                    match_confidence=0.85,
                    product_match="exact",
                    price_pln=float(o["price_pln"]) if o.get("price_pln") is not None else None,
                    price_freshness="historical_offer_row_not_live",
                    url=o.get("affiliate_url"),
                )
            )

        # 3) Affiliate feed title matches (no network, no full-CSV scan).
        for shop in FEED_SHOPS:
            by_norm = self._feed_by_norm.get(shop) or {}
            by_tok = self._feed_by_token.get(shop) or {}
            candidates = list(by_norm.get(nt) or [])
            toks = nt.split()
            if not candidates and len(toks) >= 2:
                candidates = list(by_norm.get(" ".join(toks[: min(4, len(toks))]) or "") or [])
            if not candidates:
                for tok in toks[:3]:
                    if len(tok) >= 4:
                        candidates.extend(by_tok.get(tok) or [])
            best: dict[str, str] | None = None
            best_score = 0.0
            seen_names: set[str] = set()
            for row in candidates[:120]:
                pname = row["product_name"]
                if pname in seen_names:
                    continue
                seen_names.add(pname)
                score = _token_overlap(name, pname)
                if score > best_score:
                    best_score = score
                    best = row
            if best and best_score >= 0.75:
                product_match = "exact" if best_score >= 0.95 else "likely"
                price_val = None
                try:
                    if best.get("price"):
                        price_val = float(str(best["price"]).replace(",", "."))
                except ValueError:
                    price_val = None
                hits.append(
                    StoreHit(
                        shop=shop,
                        source="affiliate_feed",
                        product_name=best["product_name"],
                        edition=_guess_edition(best["product_name"]),
                        region=_guess_region(best["product_name"]),
                        platform=_guess_platform(best["product_name"]),
                        match_confidence=round(best_score, 3),
                        product_match=product_match,
                        price_pln=price_val,
                        price_freshness="historical_feed_snapshot_not_live",
                        url=best.get("url") or None,
                    )
                )

        shops = sorted({h.shop for h in hits})
        if hits:
            status = "known_offer"
            summary = f"{len(hits)} local hit(s) across {len(shops)} shop(s)"
        else:
            status = "unknown"
            summary = "no local feed/offer evidence (UNKNOWN ≠ absent from shops)"

        return StoreCoverageResult(
            igdb_id=igdb_id,
            name=name,
            steam_appid=steam_appid,
            status=status,
            hits=hits[:20],
            shops_with_hits=shops,
            summary=summary,
        )


def analyze_candidates(
    candidates: list[dict[str, Any]],
    *,
    index: LocalStoreIndex | None = None,
    run_id: str | None = None,
    sample: str = "all_candidates_in_batch",
) -> dict[str, Any]:
    """Each coverage report carries run_id + timestamp + sample definition.

    Historical V4 discrepancy (43/57 vs 41/59) came from different samples
    (full batch vs verified-new subset) without labeling — fixed here.
    """
    import uuid
    from datetime import datetime, timezone

    idx = index or LocalStoreIndex()
    meta = idx.load()
    results: list[dict[str, Any]] = []
    known = 0
    unknown = 0
    by_shop: dict[str, int] = {}
    rid = run_id or f"cov_{uuid.uuid4().hex[:10]}"
    ts = datetime.now(timezone.utc).isoformat()
    for c in candidates:
        cov = idx.lookup(
            igdb_id=int(c["igdb_id"]),
            name=str(c.get("name") or ""),
            steam_appid=c.get("steam_appid"),
        )
        results.append(cov.to_dict())
        if cov.status == "known_offer":
            known += 1
            for s in cov.shops_with_hits:
                by_shop[s] = by_shop.get(s, 0) + 1
        else:
            unknown += 1
    verified_new = [
        c
        for c in candidates
        if not c.get("in_quenly")
        and (c.get("steam_resolution") or {}).get("status") == "verified"
    ]
    vn_known = 0
    vn_unknown = 0
    for c in verified_new:
        # Reuse already computed result when present
        status = next(
            (r["status"] for r in results if int(r["igdb_id"]) == int(c["igdb_id"])),
            "unknown",
        )
        if status == "known_offer":
            vn_known += 1
        else:
            vn_unknown += 1
    return {
        "run_id": rid,
        "timestamp": ts,
        "sample": sample,
        "sample_definitions": {
            "batch_all": {
                "n": len(candidates),
                "with_known_local_offer": known,
                "unknown_coverage": unknown,
                "ratio_label": f"{known}/{unknown} known/unknown among all {len(candidates)}",
            },
            "verified_new_only": {
                "n": len(verified_new),
                "with_known_local_offer": vn_known,
                "unknown_coverage": vn_unknown,
                "ratio_label": (
                    f"{vn_known}/{vn_unknown} known/unknown among "
                    f"{len(verified_new)} verified-new"
                ),
            },
        },
        "meta": meta,
        "candidates_analyzed": len(candidates),
        "with_known_local_offer": known,
        "unknown_coverage": unknown,
        "unknown_means": "no local evidence — not proof of absence",
        "by_shop_candidate_hits": by_shop,
        "results": results,
        "note_v4_43_vs_41": (
            "V4 43/57 was full-batch; 41/59 appeared after a second enrich pass; "
            "3/49 was verified-new-only. Always compare equal sample + run_id."
        ),
    }
