"""Local HTML rankings dashboard — not production frontend."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from . import config
from .rankings import ALL_RANKS


def _esc(v: Any) -> str:
    if v is None:
        return "—"
    return html.escape(str(v))


def render_rankings_html(report: dict[str, Any], path: Path | None = None) -> Path:
    path = path or (config.REPORTS_DIR / "rankings_report.html")
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lists = report.get("lists") or {}
    counts = report.get("counts") or {}
    stats = report.get("stats") or {}

    sections = []
    for list_name in ALL_RANKS:
        entries = lists.get(list_name) or []
        n = len(entries)
        rows = []
        for e in entries:
            cover = e.get("cover_url")
            cover_html = (
                f'<img class="cover" src="{_esc(cover)}" alt="" loading="lazy" '
                f'onerror="this.style.display=\'none\'"/>'
                if cover
                else ""
            )
            steam = e.get("steam_appid")
            steam_a = (
                f'<a href="https://store.steampowered.com/app/{int(steam)}/" '
                f'target="_blank" rel="noopener">{_esc(steam)}</a>'
                if steam
                else "—"
            )
            sig = e.get("signals") or {}
            rows.append(
                "<tr>"
                f"<td>{_esc(e.get('rank'))}</td>"
                f"<td>{cover_html}<strong>{_esc(e.get('name'))}</strong></td>"
                f"<td>{steam_a}</td>"
                f"<td>{_esc(e.get('release_date'))}</td>"
                f"<td>{_esc(e.get('source'))}</td>"
                f"<td><small>norm={_esc(sig.get('metric_norm'))} "
                f"recs={_esc(sig.get('steam_recommendations'))} "
                f"d7={_esc(sig.get('trending_d7'))}</small></td>"
                f"<td>{_esc(e.get('updated_at'))}</td>"
                f"<td>{'yes' if e.get('in_quenly') else 'no'}</td>"
                f"<td>{_esc(e.get('verification_status'))}</td>"
                f"<td>{_esc(e.get('store_coverage_status'))}</td>"
                f"<td>{_esc(', '.join(e.get('notes') or []))}</td>"
                "</tr>"
            )
        sections.append(
            f"<h2>{_esc(list_name)} — {_esc(n)} "
            f"<small>(requested top {_esc(stats.get('top_n_requested') or 100)}; not padded)</small></h2>"
            f'<div class="scroll"><table><thead><tr>'
            f"<th>#</th><th>Cover / Name</th><th>Steam</th><th>Release</th>"
            f"<th>Source</th><th>Signals</th><th>Updated</th>"
            f"<th>In Quenly</th><th>Verify</th><th>Store</th><th>Notes</th>"
            f"</tr></thead><tbody>{''.join(rows) or '<tr><td colspan=11>empty</td></tr>'}"
            f"</tbody></table></div>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="uk"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Quenly Game Rankings (local)</title>
<style>
  :root {{ --bg:#0f1115; --card:#171a21; --text:#e8ecf4; --muted:#9aa3b5; --line:#2a3344; }}
  body {{ margin:0; font-family:Segoe UI,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
  .wrap {{ max-width:1600px; margin:0 auto; padding:24px 18px 60px; }}
  h1 {{ margin:0 0 8px; }} h2 {{ margin:28px 0 10px; font-size:1.15rem; }}
  .sub {{ color:var(--muted); }}
  .chips {{ display:flex; flex-wrap:wrap; gap:8px; margin:14px 0; }}
  .chip {{ border:1px solid #445; border-radius:999px; padding:6px 12px; background:var(--card); }}
  table {{ width:100%; border-collapse:collapse; font-size:12px; }}
  th,td {{ border-bottom:1px solid var(--line); padding:7px 5px; vertical-align:top; text-align:left; }}
  th {{ color:var(--muted); position:sticky; top:0; background:#12151c; }}
  .scroll {{ overflow:auto; max-height:70vh; border:1px solid var(--line); border-radius:10px; }}
  .cover {{ width:120px; height:56px; object-fit:cover; border-radius:5px; display:block; margin-bottom:4px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; margin:12px 0; }}
  a {{ color:#7ec8ff; }}
  .warn {{ color:#f0b429; }}
</style></head><body><div class="wrap">
  <h1>Quenly · Game Rankings (local staging)</h1>
  <p class="sub">run_id=<code>{_esc(report.get('run_id'))}</code> ·
  ts=<code>{_esc(report.get('timestamp'))}</code> ·
  Ranking position ≠ import permission · Production frontend not touched</p>
  <div class="chips">
    {''.join(f'<span class="chip">{_esc(k)}: <b>{_esc(v)}</b></span>' for k,v in counts.items())}
  </div>
  <div class="card">
    <div>Popular in Quenly: <b>{_esc(report.get('popular_in_quenly'))}</b></div>
    <div>Popular missing: <b>{_esc(report.get('popular_missing'))}</b></div>
    <p class="warn" style="margin:8px 0 0">Lists are not artificially filled to 100.</p>
  </div>
  {''.join(sections)}
</div></body></html>
"""
    path.write_text(doc, encoding="utf-8")
    (config.REPORTS_DIR / "rankings_latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path
