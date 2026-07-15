"""Zapisuje WYKOP_REFRESH_TOKEN po przekierowaniu z Wykop Connect."""
from __future__ import annotations

import html
import os
import re
from pathlib import Path

PROMO_ENV_PATH = Path(os.environ.get("PROMO_ENV_PATH", "/opt/kupujpl-promo/.env"))


def save_refresh_token(rtoken: str) -> bool:
    rtoken = (rtoken or "").strip()
    if not rtoken or not PROMO_ENV_PATH.is_file():
        return False
    content = PROMO_ENV_PATH.read_text(encoding="utf-8")
    line = f"WYKOP_REFRESH_TOKEN={rtoken}"
    if re.search(r"^WYKOP_REFRESH_TOKEN=.*$", content, flags=re.MULTILINE):
        content = re.sub(r"^WYKOP_REFRESH_TOKEN=.*$", line, content, flags=re.MULTILINE)
    else:
        content = content.rstrip() + "\n" + line + "\n"
    PROMO_ENV_PATH.write_text(content, encoding="utf-8")
    return True


def callback_html(*, rtoken: str | None, saved: bool, error: str | None = None) -> str:
    safe_rtoken = html.escape(rtoken or "")
    if saved:
        body = """
        <h1>Wykop połączony!</h1>
        <p>Token zapisany. Autoposting może działać w ciągu kilku minut.</p>
        <p><a href="/">Wróć na KupujPL Gry</a></p>
        """
    elif error:
        body = f"""
        <h1>Błąd połączenia</h1>
        <p>{html.escape(error)}</p>
        <p>Spróbuj ponownie z nowym linkiem Connect.</p>
        """
    else:
        body = f"""
        <h1>Brak tokenu</h1>
        <p>W URL nie znaleziono <code>rtoken</code>.</p>
        <p>Otrzymany token: <code>{safe_rtoken or '—'}</code></p>
        """
    return f"""<!DOCTYPE html>
<html lang="pl"><head><meta charset="UTF-8"><title>Wykop Connect</title></head>
<body style="font-family:sans-serif;max-width:520px;margin:2rem auto;padding:1rem">
{body}
</body></html>"""
