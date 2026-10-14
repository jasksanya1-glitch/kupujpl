from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "static/index.html",
    "app/core/polish_counts.py",
    "app/core/home_ssr.py",
]


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    for rel in FILES:
        sftp.put(str(LOCAL / rel), f"{REMOTE}/{rel}")
        print("OK", rel)
    sftp.close()
    cmd = r'''
systemctl restart kupujpl-games
sleep 2
systemctl is-active kupujpl-games
head -n 2 /opt/kupujpl-games/static/index.html
cd /opt/kupujpl-games && python3 - <<'PY'
from pathlib import Path
import re
root = Path("app")
hits=[]
for p in root.rglob("*"):
    if not p.is_file() or p.suffix.lower() not in {".py",".js",".html",".json"}: continue
    if "design-samples" in str(p) or "layout-samples" in str(p): continue
    t=p.read_text(encoding="utf-8", errors="ignore")
    for pat in ("10 sklepów","10 sklepach","5000+","5000 gier"):
        if pat in t:
            hits.append(f"{p}:{pat}")
print("live_hits", hits)
print("legacy_marked", "UNUSED LEGACY" in Path("static/index.html").read_text(encoding="utf-8", errors="ignore"))
# quick home sanity
import urllib.request, ssl
ctx=ssl.create_default_context()
UA="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
req=urllib.request.Request("https://kupujpl.pl/games/", headers={"User-Agent":UA})
html=urllib.request.urlopen(req, timeout=30, context=ctx).read().decode()
h2=html.find('id="games-heading"'); card=html.find("ssr-game-card")
print("h2_before", h2!=-1 and card!=-1 and h2<card, "ssr", html.count("ssr-game-card"))
PY
'''
    _i, stdout, stderr = client.exec_command(cmd, timeout=90)
    sys.stdout.buffer.write(stdout.read())
    err = stderr.read()
    if err.strip():
        sys.stdout.buffer.write(b"\nSTDERR\n")
        sys.stdout.buffer.write(err[:2000])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
