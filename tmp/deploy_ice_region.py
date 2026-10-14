from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/static/theme.js",
    "app/static/region.js",
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
        "systemctl restart kupujpl-games; sleep 2; systemctl is-active kupujpl-games; "
        "python3 - <<'PY'\n"
        "import urllib.request, time\n"
        "for i in range(5):\n"
        "  try:\n"
        "    req=urllib.request.Request('https://kupujpl.pl/games/?nocache=ice6',\n"
        "      headers={'User-Agent':'Mozilla/5.0 Chrome/131','Sec-CH-UA-Mobile':'?0','Cache-Control':'no-cache'})\n"
        "    h=urllib.request.urlopen(req,timeout=20).read().decode('utf-8','replace')\n"
        "    print('status ok', len(h))\n"
        "    print('theme ice boot', \"dataset.theme='ice'\" in h or 'dataset.theme=\"ice\"' in h or \"theme='ice'\" in h)\n"
        "    print('no theme slot', 'data-theme-switch-slot' not in h)\n"
        "    print('region slot', 'data-region-switch-slot' in h)\n"
        "    print('lang slot', 'data-lang-switch-slot' in h)\n"
        "    print('theme.js v4', 'theme.js?v=4' in h)\n"
        "    print('region.js v6', 'region.js?v=6' in h)\n"
        "    print('no matrix-rain', 'matrix-rain' not in h)\n"
        "    break\n"
        "  except Exception as e:\n"
        "    print('retry', i, type(e).__name__); time.sleep(1)\n"
        "PY"
    )
    sys.stdout.buffer.write(stdout.read())
    err = stderr.read()
    if err:
        sys.stdout.buffer.write(b"ERR " + err[:600])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
