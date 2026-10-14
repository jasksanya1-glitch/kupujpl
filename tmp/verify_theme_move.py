import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

cmd = r"""
python3 <<'PY'
from pathlib import Path
import urllib.request

idx = Path("/opt/kupujpl-games/app/static/index.html").read_text(encoding="utf-8")
print("file d3-theme-slot", "d3-theme-slot" in idx)
print("file m-drawer-theme", "m-drawer-theme" in idx)
print("file theme.js", [x for x in idx.split() if "theme.js" in x][:3])
print("theme.js size", Path("/opt/kupujpl-games/app/static/theme.js").stat().st_size)

req = urllib.request.Request(
    "https://kupujpl.pl/games/?nocache=theme3",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0",
        "Sec-CH-UA-Mobile": "?0",
        "Cache-Control": "no-cache",
    },
)
with urllib.request.urlopen(req, timeout=20) as r:
    h = r.read().decode("utf-8", "replace")
    print("http status", r.status)
    print("len", len(h))
    print("live d3-theme-slot", "d3-theme-slot" in h)
    print("live m-drawer-theme", "m-drawer-theme" in h)
    print("live theme.js v3", "theme.js?v=3" in h)
    print("snippet", h[h.find("d3-tools") : h.find("d3-tools") + 280] if "d3-tools" in h else h[:300])
PY
"""

client = _connect()
_, stdout, stderr = client.exec_command(cmd)
print(stdout.read().decode("utf-8", "replace"))
err = stderr.read().decode("utf-8", "replace").strip()
if err:
    print("ERR", err[:800])
client.close()
