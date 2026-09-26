"""Upload Discover/News MVP files from local backend to production VPS."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, r"D:\CursorProjects\cursor-server-mcp")
from ssh_exec import _connect  # noqa: E402

LOCAL = Path(r"D:/CursorProjects/kupujpl-games/backend")
REMOTE = "/opt/kupujpl-games"

FILES = [
    "app/models/models.py",
    "app/core/articles.py",
    "app/core/article_images.py",
    "app/core/schema_migrate.py",
    "app/core/seo_pages.py",
    "app/core/database.py",
    "app/core/discover_candidates.py",
    "app/core/push_soft_consent.py",
    "app/core/web_push.py",
    "app/core/search_console_hooks.py",
    "app/core/game_page_html.py",
    "app/core/catalog_cache.py",
    "app/core/game_offer_selection.py",
    "app/core/db_retry.py",
    "app/main.py",
    "app/static/index.html",
    "app/static/app.js",
    "app/static/style.css",
    "app/static/redakcja.html",
    "app/static/panel3.html",
    "app/static/panel3.js",
    "app/static/push-client.js",
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
    uploaded: list[str] = []
    missing: list[str] = []
    try:
        for rel in FILES:
            lp = LOCAL / rel
            rp = f"{REMOTE}/{rel}"
            if not lp.exists():
                missing.append(rel)
                continue
            ensure_remote_dir(sftp, rp)
            sftp.put(str(lp), rp)
            uploaded.append(rel)
            print(f"OK {rel} ({lp.stat().st_size})")
    finally:
        sftp.close()
        client.close()
    print(f"UPLOADED {len(uploaded)}")
    if missing:
        print("MISSING_LOCAL", missing)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
