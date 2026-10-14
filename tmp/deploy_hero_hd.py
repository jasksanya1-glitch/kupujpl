from pathlib import Path
import sys

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect

LOCAL = Path(r"F:\Cursor\Projects\kupujpl-games\backend")
REMOTE = "/opt/kupujpl-games"
FILES = [
    "app/static/covers.js",
    "app/static/core-bundle.js",
    "app/static/desktop-concept3.css",
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
        "grep -c library_hero /opt/kupujpl-games/app/static/core-bundle.js; "
        "grep -o 'core-bundle.js?v=[0-9]*' /opt/kupujpl-games/app/static/index.html | head -1"
    )
    sys.stdout.buffer.write(stdout.read())
    err = stderr.read()
    if err:
        sys.stdout.buffer.write(b"ERR " + err[:400])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
