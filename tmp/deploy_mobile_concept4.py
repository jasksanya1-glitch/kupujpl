"""Deploy Mobile Concept #4 frontend + related backend files to VPS."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect  # noqa: E402

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"

FILES = [
    "app/static/mobile-concept4.css",
    "app/static/index.html",
    "app/static/app.js",
    "app/static/style.css",
    "app/main.py",
    "app/core/game_page_html.py",
    "app/core/seo_pages.py",
]


def ensure_remote_dir(sftp, remote_path: str) -> None:
    parts = remote_path.split("/")[:-1]
    cur = ""
    for part in parts:
        if not part:
            continue
        cur += "/" + part
        try:
            sftp.stat(cur)
        except OSError:
            try:
                sftp.mkdir(cur)
            except OSError:
                pass


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    uploaded: list[str] = []
    try:
        for rel in FILES:
            lp = LOCAL / rel
            rp = f"{REMOTE}/{rel}"
            if not lp.exists():
                print(f"MISSING {rel}")
                return 1
            ensure_remote_dir(sftp, rp)
            sftp.put(str(lp), rp)
            uploaded.append(rel)
            print(f"OK {rel} ({lp.stat().st_size})")
    finally:
        sftp.close()

    cmds = [
        f"ls -la {REMOTE}/app/static/mobile-concept4.css "
        f"{REMOTE}/app/static/index.html {REMOTE}/app/static/app.js",
        "grep -oE 'mobile-concept4.css\\?v=[0-9]+|app\\.js\\?v=[0-9]+|m-hero-art|m-bottom-nav|card-shops' "
        f"{REMOTE}/app/static/index.html {REMOTE}/app/static/app.js | sort -u | head -40",
        "systemctl restart kupujpl-games",
        "sleep 2",
        "systemctl is-active kupujpl-games",
        "curl -sS -A 'Mozilla/5.0' https://kupujpl.pl/games/ | "
        "grep -oE 'mobile-concept4.css\\?v=[0-9]+|app\\.js\\?v=[0-9]+|m-hero-art|m-bottom-nav' | sort -u",
        "node -e \"const fs=require('fs'); const s=fs.readFileSync('/opt/kupujpl-games/app/static/app.js','utf8'); try{new Function(s); console.log('app.js syntax OK');}catch(e){console.error('app.js syntax FAIL', e.message); process.exit(1);}\"",
    ]
    for cmd in cmds:
        print(f">> {cmd}")
        _, stdout, stderr = client.exec_command(cmd)
        code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", "replace").strip()
        err = stderr.read().decode("utf-8", "replace").strip()
        if out:
            print(out)
        if err:
            print("ERR", err)
        print("exit", code)

    client.close()
    print(f"UPLOADED {len(uploaded)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
