import sys
from pathlib import Path

sys.path.insert(0, r"F:\Cursor\Projects\cursor-server-mcp")
import ssh_exec  # noqa: E402

html = Path(r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.html").read_text(
    encoding="utf-8"
)
print("html", ssh_exec.write_file("/opt/kupujpl-games/app/static/panel3.html", html))

r = ssh_exec.run_command(
    "systemctl restart kupujpl-games.service && sleep 3 && systemctl is-active kupujpl-games",
    timeout_sec=45,
)
print("restart", r.get("stdout"), r.get("stderr"), r.get("exit_code"))

r2 = ssh_exec.run_command(
    "grep -n 'scan-all\\|btn-start-all\\|start_requested' "
    "/opt/kupujpl-games/app/static/panel3.html "
    "/opt/kupujpl-games/app/static/panel3.js "
    "/opt/kupujpl-games/app/main.py "
    "/opt/kupujpl-games/app/parsers/tier_a_scan_state.py | head -30",
    timeout_sec=20,
)
print(r2.get("stdout", ""))

# syntax check
r3 = ssh_exec.run_command(
    "cd /opt/kupujpl-games && ./venv/bin/python -c "
    "\"from app.main import app; print('routes', any(getattr(r,'path',None)=='/api/admin/tier-a/scan-all' for r in app.routes))\"",
    timeout_sec=40,
)
print("import", r3.get("stdout"), r3.get("stderr", "")[:800], r3.get("exit_code"))
