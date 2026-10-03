import sys
from pathlib import Path

sys.path.insert(0, r"F:\Cursor\Projects\cursor-server-mcp")
import ssh_exec  # noqa: E402

files = [
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.js",
        "/opt/kupujpl-games/app/static/panel3.js",
    ),
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.html",
        "/opt/kupujpl-games/app/static/panel3.html",
    ),
]
for local, remote in files:
    print(remote, ssh_exec.write_file(remote, Path(local).read_text(encoding="utf-8")))

r = ssh_exec.run_command(
    "grep -n 'PANEL3_PATH\\|games/panel3#' /opt/kupujpl-games/app/static/panel3.js | sed -n '1,15p'",
    timeout_sec=15,
)
print(r.get("stdout", ""))
