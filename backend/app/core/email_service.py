"""Send transactional email for KupujPL Games."""
from __future__ import annotations

import os
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr

BASE_URL = os.getenv("GAMES_BASE_URL", "https://kupujpl.pl/games").rstrip("/")

SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587") or "587")
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_RAW = (os.getenv("SMTP_FROM") or SMTP_USER or "noreply@kupujpl.pl").strip()
_SMTP_FROM_NAME_ENV = (os.getenv("SMTP_FROM_NAME") or "").strip()
_smtp_from_name_raw, _smtp_from_addr_raw = parseaddr(SMTP_FROM_RAW)
SMTP_FROM_ADDR = (_smtp_from_addr_raw or SMTP_FROM_RAW or SMTP_USER or "noreply@kupujpl.pl").strip()
SMTP_FROM_NAME = (_SMTP_FROM_NAME_ENV or _smtp_from_name_raw or "KupujPl").strip()
SMTP_TLS = os.getenv("SMTP_TLS", "auto").strip().lower()
SMTP_SSL = os.getenv("SMTP_SSL", "").strip().lower() in ("1", "true", "yes", "on")


def _tls_enabled() -> bool:
    if SMTP_TLS in ("0", "false", "off", "no"):
        return False
    if SMTP_TLS in ("1", "true", "on", "yes"):
        return True
    return SMTP_PORT not in (25, 2525) and SMTP_HOST not in ("127.0.0.1", "localhost", "::1")


def send_email(
    to_email: str,
    subject: str,
    body: str,
    *,
    html_body: str | None = None,
) -> None:
    if not SMTP_HOST:
        raise RuntimeError("SMTP nie jest skonfigurowany (brak SMTP_HOST)")

    if html_body:
        msg: MIMEText | MIMEMultipart = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")

    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = formataddr((str(Header(SMTP_FROM_NAME, "utf-8")), SMTP_FROM_ADDR))
    msg["To"] = to_email

    use_auth = bool(SMTP_USER and SMTP_PASSWORD)
    if SMTP_SSL:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            if use_auth:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            if _tls_enabled():
                server.starttls()
            if use_auth:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)


def send_reset_password_email(to_email: str, code: str) -> None:
    reset_url = f"{BASE_URL}/reset-password?code={code}"
    subject = "Reset hasła — KupujPL Gry"
    body = (
        "Cześć!\n\n"
        "Otrzymałeś tę wiadomość, ponieważ ktoś poprosił o reset hasła do konta KupujPL Gry.\n\n"
        "Ustaw nowe hasło (kliknij link lub skopiuj do przeglądarki):\n\n"
        f"{reset_url}\n\n"
        "Link jest ważny 1 godzinę.\n"
        "Jeśli to nie Ty prosiłeś o reset, zignoruj tę wiadomość.\n"
    )
    html_body = f"""<!DOCTYPE html>
<html lang="pl">
<body style="font-family:system-ui,sans-serif;line-height:1.5;color:#111;">
  <p>Cześć!</p>
  <p>Otrzymałeś tę wiadomość, ponieważ ktoś poprosił o <strong>reset hasła</strong> do konta KupujPL Gry.</p>
  <p style="margin:24px 0;">
    <a href="{reset_url}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600;">
      Ustaw nowe hasło
    </a>
  </p>
  <p style="font-size:13px;color:#555;">Link jest ważny 1 godzinę. Jeśli przycisk nie działa, wklej ten adres w przeglądarce:<br>
  <a href="{reset_url}">{reset_url}</a></p>
  <p style="font-size:13px;color:#777;">Jeśli to nie Ty prosiłeś o reset, zignoruj tę wiadomość.</p>
</body>
</html>"""
    send_email(to_email, subject, body, html_body=html_body)


def send_price_alert_email(
    to_email: str,
    *,
    game_title: str,
    best_price_pln: float,
    shop_name: str,
    baseline_pln: float | None,
    drop_pln: float,
    game_url: str,
) -> None:
    subject = f"Spadek ceny: {game_title} — {best_price_pln:.2f} zł"
    baseline_line = f"Poprzednio: {baseline_pln:.2f} zł\n" if baseline_pln else ""
    body = (
        f"Cześć!\n\n"
        f"Cena gry {game_title} spadła.\n\n"
        f"Teraz: {best_price_pln:.2f} zł ({shop_name})\n"
        f"{baseline_line}"
        f"Oszczędność: {drop_pln:.2f} zł\n\n"
        f"Zobacz porównanie:\n{game_url}\n\n"
        f"— KupujPL Gry\n"
    )
    html_body = f"""<!DOCTYPE html>
<html lang="pl">
<body style="font-family:system-ui,sans-serif;line-height:1.5;color:#111;">
  <p>Cześć!</p>
  <p>Cena gry <strong>{game_title}</strong> spadła.</p>
  <p style="font-size:18px;"><strong>{best_price_pln:.2f} zł</strong> — {shop_name}</p>
  {"<p>Poprzednio: " + f"{baseline_pln:.2f} zł" + "</p>" if baseline_pln else ""}
  <p>Oszczędność: <strong>{drop_pln:.2f} zł</strong></p>
  <p style="margin:24px 0;">
    <a href="{game_url}" style="display:inline-block;background:#2563eb;color:#fff;text-decoration:none;padding:12px 20px;border-radius:8px;font-weight:600;">
      Porównaj oferty
    </a>
  </p>
</body>
</html>"""
    send_email(to_email, subject, body, html_body=html_body)
