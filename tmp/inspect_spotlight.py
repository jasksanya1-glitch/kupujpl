import json
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

cmds = [
    "cat /opt/kupujpl-games/app/data/home_curation.json",
    "grep -RIn 'hero-witcher' /opt/kupujpl-games/app --include='*.html' --include='*.js' --include='*.css' --include='*.py' | sed -n '1,40p'",
    "ls -la /opt/kupujpl-games/app/static/img/hero-witcher* 2>/dev/null || true",
    (
        "curl -sS -A 'Mozilla/5.0' https://kupujpl.pl/games/api/home | "
        "python3 -c \"import sys,json; d=json.load(sys.stdin); "
        "print('spotlight', len(d.get('spotlight') or [])); "
        "[print(i+1, g.get('slug'), '|', g.get('title'), '|', (g.get('cover_image') or '')[:100], '|', g.get('best_price_pln')) "
        "for i,g in enumerate(d.get('spotlight') or [])]; "
        "nd=(d.get('new_deals') or [{}])[0]; print('new_deals0', nd.get('slug'), nd.get('title'))\""
    ),
]


def main() -> int:
    client = _connect()
    for cmd in cmds:
        print(">>", cmd[:140])
        _, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace").strip()
        print(out[:5000])
        if err:
            print("ERR", err[:800])
        print("---")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
