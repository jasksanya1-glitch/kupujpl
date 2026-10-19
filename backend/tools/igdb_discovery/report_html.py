"""Local HTML report for discovery review + approval actions (no secrets)."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from . import config

BUCKET_COLORS = {
    "APPROVABLE": "#1b7f4a",
    "NEEDS_REVIEW": "#b37b00",
    "REJECTED": "#a12828",
    "ALREADY_EXISTS": "#3a5a7a",
    "F2P_DEFERRED": "#6b4ea3",
    "QUARANTINE": "#555555",
}


def _esc(v: Any) -> str:
    if v is None:
        return "—"
    return html.escape(str(v))


def _steam_cover(appid: Any) -> str:
    if not appid:
        return ""
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{int(appid)}/header.jpg"


def _steam_url(appid: Any) -> str:
    if not appid:
        return ""
    return f"https://store.steampowered.com/app/{int(appid)}/"


def render_html_report(report: dict[str, Any], path: Path | None = None) -> Path:
    path = path or (config.REPORTS_DIR / "discovery_report.html")
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    rows = report.get("candidates") or []
    buckets = report.get("bucket_counts") or {}
    summary = report.get("summary") or {}
    known = report.get("known_problem_games") or []
    cats = report.get("category_counts") or {}
    queues = (report.get("import_queues") or {}).get("counts") or {}
    store = report.get("store_coverage") or {}
    top20 = report.get("top20_priority") or []

    order = ["APPROVABLE", "NEEDS_REVIEW", "F2P_DEFERRED", "QUARANTINE", "ALREADY_EXISTS", "REJECTED"]
    rank = {b: i for i, b in enumerate(order)}
    rows_sorted = sorted(
        rows,
        key=lambda r: (
            rank.get((r.get("review") or {}).get("bucket"), 99),
            -float((r.get("review") or {}).get("scan_priority") or 0),
        ),
    )

    chips = "".join(
        f'<span class="chip" style="border-color:{BUCKET_COLORS.get(k,"#666")}">'
        f"{_esc(k)}: <b>{_esc(v)}</b></span>"
        for k, v in sorted(buckets.items(), key=lambda kv: rank.get(kv[0], 99))
    )
    queue_chips = "".join(
        f'<span class="chip">{_esc(k)}: <b>{_esc(v)}</b></span>' for k, v in queues.items()
    )

    known_rows = []
    for k in known:
        known_rows.append(
            "<tr>"
            f'<td>{_esc(k.get("name"))}</td>'
            f'<td>{_esc(k.get("igdb_id"))}</td>'
            f'<td>{_esc(k.get("expected_steam"))}</td>'
            f'<td>{_esc(k.get("resolved_steam"))}</td>'
            f'<td>{"PASS" if k.get("pass") else "FAIL"}</td>'
            f'<td>{_esc(k.get("note") or (k.get("resolution") or {}).get("reason"))}</td>'
            "</tr>"
        )

    top_rows = []
    for t in top20:
        top_rows.append(
            "<tr>"
            f'<td>{_esc(t.get("rank"))}</td>'
            f'<td>{_esc(t.get("name"))}</td>'
            f'<td>{_esc(t.get("igdb_id"))}</td>'
            f'<td>{_esc(t.get("steam_appid"))}</td>'
            f'<td>{_esc(t.get("import_queue"))}</td>'
            f'<td>{_esc(t.get("priority"))}</td>'
            f'<td>{_esc(t.get("store_coverage"))}</td>'
            f'<td>{_esc(t.get("reason"))}</td>'
            "</tr>"
        )

    body_rows = []
    for r in rows_sorted:
        rev = r.get("review") or {}
        steam = r.get("steam") or {}
        match = r.get("match") or {}
        pop = r.get("popularity") or {}
        reso = r.get("steam_resolution") or {}
        prio = r.get("priority_breakdown") or {}
        cov = r.get("store_coverage") or {}
        iq = r.get("import_queue") or {}
        bucket = rev.get("bucket") or "?"
        color = BUCKET_COLORS.get(bucket, "#444")
        appid = r.get("steam_appid")
        cover = _steam_cover(appid)
        steam_link = _steam_url(appid)
        cover_html = (
            f'<img class="cover" src="{_esc(cover)}" alt="" loading="lazy" '
            f'onerror="this.style.display=\'none\'"/>'
            if cover
            else ""
        )
        steam_a = (
            f'<a href="{_esc(steam_link)}" target="_blank" rel="noopener">Steam</a>'
            if steam_link
            else "—"
        )
        igdb_id = r.get("igdb_id")
        actions = (
            f'<div class="actions" data-igdb="{_esc(igdb_id)}">'
            f'<button type="button" data-act="approve">APPROVE</button>'
            f'<button type="button" data-act="reject">REJECT</button>'
            f'<button type="button" data-act="defer">DEFER</button>'
            f'<span class="act-msg"></span></div>'
        )
        body_rows.append(
            "<tr>"
            f'<td>{cover_html}<strong>{_esc(r.get("name"))}</strong><br>'
            f'<small>IGDB {_esc(igdb_id)}</small><br>{steam_a}</td>'
            f'<td>{_esc(appid)}<br><small>{_esc(steam.get("steam_name"))}</small></td>'
            f'<td>{_esc(rev.get("pc_release_date"))}<br><small>{_esc(steam.get("app_type"))} · '
            f'{_esc(rev.get("monetization"))}</small></td>'
            f'<td>{_esc(pop.get("category"))}<br><small>{_esc(pop.get("metric_name"))} '
            f'norm={_esc(pop.get("metric_norm"))}</small></td>'
            f'<td>{"yes" if r.get("in_quenly") else "no"}</td>'
            f'<td><span class="bucket" style="background:{color}">{_esc(bucket)}</span>'
            f'<br><small>queue={_esc(iq.get("queue"))}</small>'
            f'<br><small>reso={_esc(reso.get("status"))}</small></td>'
            f'<td>{_esc(rev.get("reason"))}<br>'
            f'<small>store={_esc(cov.get("status"))} {_esc(cov.get("summary"))}</small></td>'
            f'<td>{_esc(rev.get("scan_priority"))}<br><small>{_esc(prio.get("notes"))}</small></td>'
            f'<td>{_esc(match.get("status"))}<br>{actions}</td>'
            "</tr>"
        )

    istore = report.get("steam_istore") or {}
    go = report.get("go_nogo") or {}
    yb = report.get("your_boyfriend_explanation") or {}
    load = report.get("load_estimate") or {}
    audit = report.get("candidate_audit") or {}

    doc = f"""<!DOCTYPE html>
<html lang="uk">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Quenly IGDB Discovery V4</title>
<style>
  :root {{ --bg:#0f1115; --card:#171a21; --text:#e8ecf4; --muted:#9aa3b5; --line:#2a3344; }}
  body {{ margin:0; font-family:Segoe UI,system-ui,sans-serif; background:var(--bg); color:var(--text); }}
  .wrap {{ max-width:1600px; margin:0 auto; padding:24px 18px 60px; }}
  h1 {{ margin:0 0 8px; font-size:1.6rem; }}
  h2 {{ margin:32px 0 12px; font-size:1.2rem; }}
  .sub {{ color:var(--muted); margin-bottom:18px; line-height:1.5; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:8px; margin:16px 0 22px; }}
  .chip {{ border:1px solid #444; border-radius:999px; padding:6px 12px; font-size:13px; background:var(--card); }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin-bottom:16px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ border-bottom:1px solid var(--line); padding:8px 6px; vertical-align:top; text-align:left; }}
  th {{ color:var(--muted); font-weight:600; position:sticky; top:0; background:#12151c; }}
  .bucket {{ display:inline-block; padding:2px 8px; border-radius:6px; font-size:11px; font-weight:700; color:#fff; }}
  .scroll {{ overflow:auto; max-height:75vh; border:1px solid var(--line); border-radius:10px; }}
  code {{ background:#0b0d12; padding:1px 5px; border-radius:4px; }}
  .warn {{ color:#f0b429; }}
  .ok {{ color:#3ddc97; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:10px; }}
  .stat {{ background:#12151c; border:1px solid var(--line); border-radius:10px; padding:12px; }}
  .stat b {{ display:block; font-size:1.35rem; margin-top:4px; }}
  .cover {{ display:block; width:140px; height:66px; object-fit:cover; border-radius:6px; margin-bottom:6px; background:#0b0d12; }}
  .actions {{ display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }}
  .actions button {{ font-size:11px; padding:4px 8px; border-radius:6px; border:1px solid #445; background:#1c2433; color:#e8ecf4; cursor:pointer; }}
  .actions button[data-act="approve"] {{ border-color:#1b7f4a; color:#3ddc97; }}
  .actions button[data-act="reject"] {{ border-color:#a12828; color:#ff8f8f; }}
  .act-msg {{ font-size:11px; color:var(--muted); width:100%; }}
  a {{ color:#7ec8ff; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Quenly · IGDB Game Discovery V4</h1>
  <p class="sub">
    Mode: <code>{_esc(report.get("mode"))}</code> ·
    Staging writes: <code>{_esc(report.get("wrote_staging"))}</code> ·
    Production writes: <b>none</b> ·
    APPROVE = staging only (never publishes to Quenly).
  </p>
  <div class="chips">{chips}</div>
  <div class="chips">{queue_chips}</div>

  <div class="grid">
    <div class="stat">Analyzed<b>{_esc(summary.get("analyzed") or len(rows))}</b></div>
    <div class="stat">Missing in Quenly<b>{_esc(summary.get("missing_in_quenly"))}</b></div>
    <div class="stat">Verified new<b>{_esc(summary.get("verified_new_candidates"))}</b></div>
    <div class="stat">APPROVABLE<b>{_esc(summary.get("approvable"))}</b></div>
    <div class="stat">Store known (local)<b>{_esc(store.get("with_known_local_offer"))}</b></div>
    <div class="stat">Store UNKNOWN<b>{_esc(store.get("unknown_coverage"))}</b></div>
    <div class="stat">Wrong Steam (known)<b>{_esc(summary.get("wrong_steam_appid_in_known_set"))}</b></div>
    <div class="stat">IGDB req / pass (est.)<b>{_esc(load.get("igdb_requests_per_pass"))}</b></div>
  </div>

  <div class="card" style="margin-top:16px">
    <div><b>Steam IStoreService:</b> {_esc((istore.get("message")))}</div>
    <div><b>Store coverage:</b> {_esc(store.get("unknown_means"))}</div>
    <div><b>Audit note:</b> {_esc(audit.get("approvable_why_few"))}</div>
    <p class="warn" style="margin:10px 0 0">{_esc(summary.get("security_note"))}</p>
    <p class="sub">Approval API: start <code>python -m tools.igdb_discovery.serve_approval</code> then use buttons below.</p>
  </div>

  <h2>Top 20 priority</h2>
  <div class="scroll"><table>
    <thead><tr><th>#</th><th>Name</th><th>IGDB</th><th>Steam</th><th>Queue</th><th>Priority</th><th>Store</th><th>Reason</th></tr></thead>
    <tbody>{"".join(top_rows) or "<tr><td colspan=8>n/a</td></tr>"}</tbody>
  </table></div>

  <h2>Known problem games (regression)</h2>
  <div class="scroll"><table>
    <thead><tr><th>Name</th><th>IGDB</th><th>Expected Steam</th><th>Resolved</th><th>Result</th><th>Note</th></tr></thead>
    <tbody>{"".join(known_rows) or "<tr><td colspan=6>n/a</td></tr>"}</tbody>
  </table></div>

  <h2>Your Boyfriend (prior APPROVABLE vs 0 in batch)</h2>
  <div class="card"><p>{_esc(yb.get("why_prior_approvable_but_zero_in_50"))}</p></div>

  <h2>Balanced cohort + approval</h2>
  <p class="sub">Categories: {_esc(cats)}</p>
  <div class="scroll"><table>
    <thead><tr>
      <th>Cover / Game</th><th>Steam</th><th>Release</th><th>Popularity</th>
      <th>In Quenly</th><th>Status / Queue</th><th>Reason / Store</th><th>Priority</th><th>Actions</th>
    </tr></thead>
    <tbody>{"".join(body_rows)}</tbody>
  </table></div>

  <h2>GO / NO-GO</h2>
  <div class="card">
    <p><b>{_esc(go.get("verdict"))}</b></p>
    <p class="sub">{_esc(go.get("detail"))}</p>
  </div>
</div>
<script>
(function() {{
  const API = (window.DISCOVERY_APPROVAL_API || "http://127.0.0.1:8766");
  document.querySelectorAll(".actions button").forEach(btn => {{
    btn.addEventListener("click", async () => {{
      const wrap = btn.closest(".actions");
      const igdb = wrap.getAttribute("data-igdb");
      const action = btn.getAttribute("data-act");
      const msg = wrap.querySelector(".act-msg");
      msg.textContent = "…";
      try {{
        const res = await fetch(API + "/api/decision", {{
          method: "POST",
          headers: {{"Content-Type": "application/json"}},
          body: JSON.stringify({{ igdb_id: Number(igdb), action }})
        }});
        const data = await res.json();
        if (data.ok) {{
          msg.textContent = data.new_status + " (staging only)";
          msg.className = "act-msg ok";
        }} else {{
          msg.textContent = data.error || "failed";
          msg.className = "act-msg warn";
        }}
      }} catch (e) {{
        msg.textContent = "Start serve_approval on :8766";
        msg.className = "act-msg warn";
      }}
    }});
  }});
}})();
</script>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")
    safe = {k: v for k, v in report.items() if k not in {"raw_token", "credentials"}}
    (config.REPORTS_DIR / "discovery_report.json").write_text(
        json.dumps(safe, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path
