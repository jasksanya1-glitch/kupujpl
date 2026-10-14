import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

cmd = r"""
python3 <<'PY'
from pathlib import Path
import urllib.request, time
idx = Path('/opt/kupujpl-games/app/static/index.html').read_text(encoding='utf-8')
print('file d3-lang-slot', 'd3-lang-slot' in idx)
print('file m-drawer-lang', 'm-drawer-lang' in idx)
print('file i18n31', 'i18n.js?v=31' in idx)
for i in range(6):
    try:
        req = urllib.request.Request(
            'https://kupujpl.pl/games/?nocache=lang31b',
            headers={
                'User-Agent': 'Mozilla/5.0 Chrome/131',
                'Sec-CH-UA-Mobile': '?0',
                'Cache-Control': 'no-cache',
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            h = r.read().decode('utf-8', 'replace')
            print('status', r.status, 'len', len(h))
            print('live d3-lang-slot', 'd3-lang-slot' in h)
            print('live m-drawer-lang', 'm-drawer-lang' in h)
            print('live i18n31', 'i18n.js?v=31' in h)
            print('live css8', 'desktop-concept3.css?v=8' in h)
            break
    except Exception as e:
        print('retry', i, type(e).__name__)
        time.sleep(1)
PY
"""

client = _connect()
_, stdout, stderr = client.exec_command(cmd)
sys.stdout.buffer.write(stdout.read())
err = stderr.read()
if err:
    sys.stdout.buffer.write(b"ERR " + err[:800])
client.close()
