from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "scripts/validate_sitemaps.py",
    "app/static/index.html",
    "app/core/home_ssr.py",
]


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    for rel in FILES:
        sftp.put(str(LOCAL / rel), f"{REMOTE}/{rel}")
        print("OK", rel)
    sftp.close()
    cmd = r"""
systemctl restart kupujpl-games
sleep 2
systemctl is-active kupujpl-games
cd /opt/kupujpl-games && python3 -m scripts.validate_sitemaps --sample 20 --workers 2
cd /opt/kupujpl-games && python3 -c '
import urllib.request, re, ssl
ctx=ssl.create_default_context()
UA="Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
def get(u):
    req=urllib.request.Request(u, headers={"User-Agent":UA,"Cache-Control":"no-cache"})
    return urllib.request.urlopen(req, timeout=30, context=ctx).read().decode()
html=get("https://kupujpl.pl/games/")
print("placeholder_left", "__STORE_COUNT__" in html, "__GAME_COUNT__" in html)
print("meta_has_10_sklep", bool(re.search(r"content=\"[^\"]*10 sklep", html)))
print("ssr_games", html.count("ssr-game-card"), "ssr_news", html.count("home-news-item"), "h1", len(re.findall(r"<h1", html, re.I)))
promo=get("https://kupujpl.pl/games/promocje")
for slug,good,bad in [("frostpunk-2","48.03","28.49"),("elden-ring","199.15","186.89"),("black-myth-wukong-2358720","154.24","145.39")]:
    print(slug, "good", good in promo, "bad", bad in promo)
print("DONE")
'
"""
    _in, stdout, stderr = client.exec_command(cmd, timeout=180)
    sys.stdout.buffer.write(stdout.read())
    err = stderr.read()
    if err.strip():
        sys.stdout.buffer.write(b"\nSTDERR\n")
        sys.stdout.buffer.write(err[:3000])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
