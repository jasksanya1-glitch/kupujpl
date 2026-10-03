"""Upload security hotfix files only (preserve home_feeds + site_tracking)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect  # noqa: E402

LOCAL = Path(r"D:/CursorProjects/kupujpl-games/backend")
REMOTE = "/opt/kupujpl-games"

FILES = [
    "app/core/html_sanitize.py",
    "app/core/json_ld_safe.py",
    "app/core/panel3_auth.py",
    "app/core/articles.py",
    "app/core/seo_pages.py",
    "app/main.py",
    "app/static/panel3.js",
    "requirements.txt",
]


def ensure_remote_dir(sftp, remote_path: str) -> None:
    parts = remote_path.split("/")[:-1]
    cur = ""
    for part in parts:
        if not part:
            continue
        cur += "/" + part
        try:
            sftp.stat(cur)
        except OSError:
            try:
                sftp.mkdir(cur)
            except OSError:
                pass


def main() -> int:
    client = _connect()
    sftp = client.open_sftp()
    try:
        for rel in FILES:
            lp = LOCAL / rel
            rp = f"{REMOTE}/{rel}"
            if not lp.exists():
                print("MISSING", rel)
                return 1
            ensure_remote_dir(sftp, rp)
            sftp.put(str(lp), rp)
            print("OK", rel, lp.stat().st_size)
    finally:
        sftp.close()
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
