from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/static/mobile-concept4.css",
    "app/static/index.html",
    "app/core/game_page_html.py",
    "app/core/seo_pages.py",
]


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    try:
        for rel in FILES:
            lp = LOCAL / rel
            sftp.put(str(lp), f"{REMOTE}/{rel}")
            print(f"OK {rel} ({lp.stat().st_size})")
    finally:
        sftp.close()

    _, stdout, stderr = client.exec_command(
        "systemctl restart kupujpl-games; sleep 1; systemctl is-active kupujpl-games; "
        "curl -sS -A 'Mozilla/5.0' https://kupujpl.pl/games/ | "
        "grep -oE 'mobile-concept4.css\\?v=[0-9]+' | head -1"
    )
    print(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        print("ERR", err)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
