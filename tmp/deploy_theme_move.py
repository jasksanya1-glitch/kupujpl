from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/static/theme.js",
    "app/static/desktop-concept3.css",
    "app/static/mobile-concept4.css",
    "app/static/index.html",
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
        "curl -sS -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' "
        "-H 'Sec-CH-UA-Mobile: ?0' https://kupujpl.pl/games/ | "
        "python3 -c \"import sys,re; h=sys.stdin.read(); "
        "print('d3-theme-slot', 'd3-theme-slot' in h); "
        "print('m-drawer-theme', 'm-drawer-theme' in h); "
        "print('theme.js', re.findall(r'theme\\.js\\?v=\\d+', h)); "
        "print('css', re.findall(r'(?:desktop-concept3|mobile-concept4)\\.css\\?v=\\d+', h))\""
    )
    print(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        print("ERR", err[:500])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
