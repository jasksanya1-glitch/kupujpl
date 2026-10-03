import sys
import time
from pathlib import Path

sys.path.insert(0, r"F:\Cursor\Projects\cursor-server-mcp")
import ssh_exec  # noqa: E402

files = [
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\parsers\tier_a_scan_state.py",
        "/opt/kupujpl-games/app/parsers/tier_a_scan_state.py",
    ),
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\main.py",
        "/opt/kupujpl-games/app/main.py",
    ),
]
for local, remote in files:
    print(remote, ssh_exec.write_file(remote, Path(local).read_text(encoding="utf-8")))

print(
    ssh_exec.run_command(
        "systemctl restart kupujpl-games.service && sleep 4 && systemctl is-active kupujpl-games",
        timeout_sec=45,
    ).get("stdout")
)

script = r'''
import os, urllib.request, json, time
from dotenv import load_dotenv
load_dotenv("/opt/kupujpl-games/.env")
code = os.environ.get("PANEL3_ACCESS_CODE") or ""
import sys
sys.path.insert(0, "/opt/kupujpl-games")
os.chdir("/opt/kupujpl-games")
from app.parsers.tier_a_scan_state import load_vps_state, is_vps_scan_running
print("after_restart", load_vps_state().get("phase"), "running", is_vps_scan_running())
req = urllib.request.Request(
    "http://127.0.0.1:8010/api/admin/tier-a/scan-all",
    data=b"{}",
    headers={"X-Panel3-Code": code, "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    print("scan-all", resp.status, resp.read().decode()[:600])
time.sleep(3)
v = load_vps_state()
print("vps_now", v.get("phase"), v.get("games_done"), v.get("current_game"), v.get("updated_at"))
'''
ssh_exec.write_file("/tmp/restart_and_scan.py", script)
r = ssh_exec.run_command(
    "cd /opt/kupujpl-games && ./venv/bin/python /tmp/restart_and_scan.py",
    timeout_sec=60,
)
print(r.get("stdout", ""))
print(r.get("stderr", "")[:500])
