from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/static/i18n.js",
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
        "python3 - <<'PY'\n"
        "import urllib.request\n"
        "req=urllib.request.Request('https://kupujpl.pl/games/?nocache=lang31',\n"
        " headers={'User-Agent':'Mozilla/5.0 Chrome/131','Sec-CH-UA-Mobile':'?0','Cache-Control':'no-cache'})\n"
        "h=urllib.request.urlopen(req,timeout=20).read().decode('utf-8','replace')\n"
        "print('d3-lang-slot', 'd3-lang-slot' in h)\n"
        "print('m-drawer-lang', 'm-drawer-lang' in h)\n"
        "print('i18n v31', 'i18n.js?v=31' in h)\n"
        "print('css8', 'desktop-concept3.css?v=8' in h)\n"
        "print('css13', 'mobile-concept4.css?v=13' in h)\n"
        "PY"
    )
    print(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        print("ERR", err[:500])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
