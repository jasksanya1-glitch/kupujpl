import sys
from pathlib import Path

sys.path.insert(0, r"F:\Cursor\Projects\cursor-server-mcp")
import ssh_exec  # noqa: E402

files = [
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\parsers\tier_a_scan_state.py",
        "/opt/kupujpl-games/app/parsers/tier_a_scan_state.py",
    ),
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\parsers\daily_tier_a_pipeline.py",
        "/opt/kupujpl-games/app/parsers/daily_tier_a_pipeline.py",
    ),
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\main.py",
        "/opt/kupujpl-games/app/main.py",
    ),
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.js",
        "/opt/kupujpl-games/app/static/panel3.js",
    ),
]
for local, remote in files:
    print(remote, ssh_exec.write_file(remote, Path(local).read_text(encoding="utf-8")))

# bump js cache in html
html_path = "/opt/kupujpl-games/app/static/panel3.html"
html = Path(r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.html").read_text(
    encoding="utf-8"
)
if "panel3.js?v=27" in html:
    html = html.replace("panel3.js?v=27", "panel3.js?v=28")
    Path(r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.html").write_text(
        html, encoding="utf-8"
    )
print("html", ssh_exec.write_file(html_path, html))

r = ssh_exec.run_command(
    "systemctl restart kupujpl-games.service && sleep 4 && systemctl is-active kupujpl-games",
    timeout_sec=45,
)
print("restart", r.get("stdout"), r.get("exit_code"))

# clear stale + start via code from env
script = r'''
import os, json
from pathlib import Path
from dotenv import load_dotenv
load_dotenv("/opt/kupujpl-games/.env")
code = os.environ.get("PANEL3_ACCESS_CODE") or os.environ.get("PANEL3_CODE") or ""
print("code_len", len(code))

# import app helpers
import sys
sys.path.insert(0, "/opt/kupujpl-games")
os.chdir("/opt/kupujpl-games")
from app.parsers.tier_a_scan_state import (
    load_vps_state, is_vps_scan_running, is_running_state_fresh, mark_stale_running_as_idle
)
st = load_vps_state()
print("before", st.get("phase"), st.get("updated_at"), "fresh", is_running_state_fresh(st), "running", is_vps_scan_running())
print("after_check", load_vps_state().get("phase"))

import urllib.request
req = urllib.request.Request(
    "http://127.0.0.1:8010/api/admin/tier-a/scan-all",
    data=b"{}",
    headers={"X-Panel3-Code": code, "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode()
        print("scan-all", resp.status, body[:500])
except Exception as e:
    print("scan-all_err", e)

import time
time.sleep(2)
st2 = load_vps_state()
print("vps_now", st2.get("phase"), st2.get("updated_at"), st2.get("games_done"))
'''
ssh_exec.write_file("/tmp/fix_scan_start.py", script)
r2 = ssh_exec.run_command(
    "cd /opt/kupujpl-games && ./venv/bin/python /tmp/fix_scan_start.py",
    timeout_sec=60,
)
print(r2.get("stdout", ""))
print(r2.get("stderr", "")[:800])
