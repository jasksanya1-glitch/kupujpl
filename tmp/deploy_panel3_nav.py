import sys
from pathlib import Path

sys.path.insert(0, r"F:\Cursor\Projects\cursor-server-mcp")
import ssh_exec  # noqa: E402

files = [
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.html",
        "/opt/kupujpl-games/app/static/panel3.html",
    ),
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.js",
        "/opt/kupujpl-games/app/static/panel3.js",
    ),
    (
        r"F:\Cursor\Projects\kupujpl-games\backend\app\static\panel3.css",
        "/opt/kupujpl-games/app/static/panel3.css",
    ),
]
for local, remote in files:
    data = Path(local).read_text(encoding="utf-8")
    print(remote, ssh_exec.write_file(remote, data))

r = ssh_exec.run_command(
    "grep -c 'panel3-nav' /opt/kupujpl-games/app/static/panel3.html "
    "/opt/kupujpl-games/app/static/panel3.css "
    "/opt/kupujpl-games/app/static/panel3.js; "
    "grep -o 'panel3.css?v=[0-9]*\\|panel3.js?v=[0-9]*' /opt/kupujpl-games/app/static/panel3.html",
    timeout_sec=20,
)
print(r.get("stdout", ""))
