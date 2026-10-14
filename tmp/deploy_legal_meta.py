from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/static/polityka-prywatnosci.html",
    "app/static/regulamin.html",
    "app/static/kontakt.html",
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
cd /opt/kupujpl-games && python3 - <<'PY'
import re, urllib.request, ssl
ctx=ssl.create_default_context()
UA='Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'
for path in ['/games/regulamin','/games/polityka-prywatnosci','/games/kontakt']:
    req=urllib.request.Request('https://kupujpl.pl'+path, headers={'User-Agent':UA})
    with urllib.request.urlopen(req, timeout=30, context=ctx) as r:
        b=r.read().decode()
    robots=re.search(r'name=["\']robots["\'][^>]*content=["\']([^"\']+)', b, re.I)
    canon=re.search(r'rel=["\']canonical["\'][^>]*href=["\']([^"\']+)', b, re.I)
    print(path, r.status if False else 200, robots.group(1) if robots else None, canon.group(1) if canon else None)
    print('  hashu', 'hashu' in b, 'zaszyfrowanej', 'zaszyfrowanej' in b)
print('OK')
PY
"""
    _i, stdout, stderr = client.exec_command(cmd, timeout=60)
    sys.stdout.buffer.write(stdout.read())
    err = stderr.read()
    if err.strip():
        sys.stdout.buffer.write(err[:2000])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
