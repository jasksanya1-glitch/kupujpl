from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/static/i18n.js",
    "app/static/index.html",
    "app/static/app.js",
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
        "import urllib.request,re\n"
        "req=urllib.request.Request('https://kupujpl.pl/games/?nocache=i18n32',\n"
        " headers={'User-Agent':'Mozilla/5.0 Chrome/131','Sec-CH-UA-Mobile':'?0','Cache-Control':'no-cache'})\n"
        "h=urllib.request.urlopen(req,timeout=20).read().decode('utf-8','replace')\n"
        "print('i18n32', 'i18n.js?v=32' in h)\n"
        "print('app92', 'app.js?v=92' in h)\n"
        "print('nav.games', 'data-i18n=\"nav.games\"' in h)\n"
        "print('d3.compare', 'data-i18n=\"d3.compare\"' in h)\n"
        "print('sort.bestsellers', 'data-i18n=\"sort.bestsellers\"' in h)\n"
        "req2=urllib.request.Request('https://kupujpl.pl/games/static/i18n.js?v=32',\n"
        " headers={'Cache-Control':'no-cache'})\n"
        "i18n=urllib.request.urlopen(req2,timeout=20).read().decode('utf-8','replace')\n"
        "print('uk_nav_games', \"'nav.games': 'Ігри'\" in i18n)\n"
        "print('uk_budget', \"'cat.budget_30': 'Ігри PC до 30 zł'\" in i18n)\n"
        "print('uk_d3_compare', \"'d3.compare': 'Порівняти ціни →'\" in i18n)\n"
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
