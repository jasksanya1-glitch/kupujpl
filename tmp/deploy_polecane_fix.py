from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/static/app.js",
    "app/static/index.html",
    "app/static/mobile-concept4.css",
    "app/static/core-bundle.js",
    "app/static/covers.js",
    "app/core/game_page_html.py",
    "app/core/seo_pages.py",
]


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    try:
        for rel in FILES:
            lp = LOCAL / rel
            if not lp.exists():
                print("MISSING", rel)
                return 1
            sftp.put(str(lp), f"{REMOTE}/{rel}")
            print(f"OK {rel} ({lp.stat().st_size})")
    finally:
        sftp.close()

    cmds = [
        "systemctl restart kupujpl-games",
        "sleep 2",
        "systemctl is-active kupujpl-games",
        (
            "curl -sS -A 'Mozilla/5.0' https://kupujpl.pl/games/ | "
            "grep -oE 'mobile-concept4.css\\?v=[0-9]+|app\\.js\\?v=[0-9]+|core-bundle.js\\?v=[0-9]+|m-featured-kicker|m-featured-track' | sort -u"
        ),
        (
            "node -e \"const fs=require('fs'); const s=fs.readFileSync('/opt/kupujpl-games/app/static/app.js','utf8'); "
            "console.log(s.includes('Priority 1: owner-curated') ? 'polecane-priority OK' : 'MISSING'); "
            "console.log(s.includes('hero-witcher') ? 'WITCHER STILL PRESENT' : 'no-witcher OK');\""
        ),
    ]
    for cmd in cmds:
        print(">>", cmd[:120])
        _, stdout, stderr = client.exec_command(cmd)
        print(stdout.read().decode("utf-8", "replace").strip())
        err = stderr.read().decode("utf-8", "replace").strip()
        if err:
            print("ERR", err[:500])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
