import sys
from pathlib import Path

sys.path.insert(0, r"F:\Cursor\Projects\cursor-server-mcp")
import ssh_exec  # noqa: E402

files = [
    (r"F:\Cursor\Projects\kupujpl-games\backend\app\main.py", "/opt/kupujpl-games/app/main.py"),
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

print(
    ssh_exec.run_command(
        "systemctl restart kupujpl-games.service && sleep 3 && systemctl is-active kupujpl-games",
        timeout_sec=40,
    ).get("stdout")
)
