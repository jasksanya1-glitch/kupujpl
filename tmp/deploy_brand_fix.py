from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
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
        "req=urllib.request.Request('http://127.0.0.1:8010/',\n"
        " headers={'User-Agent':'Mozilla/5.0 Chrome/131','Sec-CH-UA-Mobile':'?0'})\n"
        "h=urllib.request.urlopen(req,timeout=15).read().decode('utf-8','replace')\n"
        "print('d3v14', 'desktop-concept3.css?v=14' in h)\n"
        "print('m4v15', 'mobile-concept4.css?v=15' in h)\n"
        "css=urllib.request.urlopen('http://127.0.0.1:8010/static/desktop-concept3.css?v=14',timeout=15).read().decode()\n"
        "print('clip_reset', 'clip-path: none' in css)\n"
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
