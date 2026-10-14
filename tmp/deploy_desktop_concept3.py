from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/main.py",
    "app/static/desktop-concept3.css",
    "app/static/mobile-concept4.css",
    "app/static/index.html",
    "app/static/app.js",
    "app/static/i18n.js",
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
        "echo '--- DESKTOP ---'; "
        "curl -sS -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0' "
        "-H 'Sec-CH-UA-Mobile: ?0' https://kupujpl.pl/games/ | "
        "python3 -c \"import sys; h=sys.stdin.read(); "
        "print('tpl', 'tpl-mobile-home-legacy' in h); "
        "print('m-hero-search', 'm-hero-search' in h); "
        "print('sort-select', 'sort-select' in h); "
        "print('m-featured-host', 'm-featured-host' in h); "
        "print('site-h1', 'site-h1' in h); "
        "print('m-hero-marketing', 'm-hero-marketing' in h); "
        "print('assets', [x for x in "
        "['desktop-concept3.css?v=6','app.js?v=88','i18n.js?v=30','mobile-concept4.css?v=11'] "
        "if x in h])\"; "
        "echo '--- MOBILE ---'; "
        "curl -sS -A 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15' "
        "-H 'Sec-CH-UA-Mobile: ?1' https://kupujpl.pl/games/ | "
        "python3 -c \"import sys; h=sys.stdin.read(); "
        "print('m-hero-search', 'm-hero-search' in h); "
        "print('sort-select', 'sort-select' in h); "
        "print('m-featured-host', 'm-featured-host' in h); "
        "print('m-hero-marketing', 'm-hero-marketing' in h); "
        "print('site-h1', 'site-h1' in h); "
        "print('tpl_left', 'tpl-mobile-home-legacy' in h)\"; "
        "echo '--- DEAL META ---'; "
        "curl -sS https://kupujpl.pl/games/api/catalog/status | "
        "python3 -c \"import sys,json; d=json.load(sys.stdin); "
        "print('games_total', d.get('games_total')); "
        "print('shops', len(d.get('offers_by_shop') or {}))\""
    )
    print(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace").strip()
    if err:
        print("ERR", err[:800])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
