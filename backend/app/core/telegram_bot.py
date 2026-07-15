"""Telegram Bot API helpers for price alerts."""
from __future__ import annotations

import logging
import os

import httpx

logger = logging.getLogger("telegram_bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}" if TELEGRAM_BOT_TOKEN else ""


def bot_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN)


def send_telegram_message(
    chat_id: str,
    text: str,
    *,
    parse_mode: str | None = None,
    disable_web_page_preview: bool = False,
) -> bool:
    if not TELEGRAM_API:
        logger.debug("Telegram bot not configured")
        return False
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        with httpx.Client(timeout=20) as client:
            r = client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            r.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("sendMessage failed: %s", exc)
        return False


def answer_callback(callback_query_id: str, text: str = "") -> None:
    if not TELEGRAM_API:
        return
    try:
        with httpx.Client(timeout=10) as client:
            client.post(
                f"{TELEGRAM_API}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id, "text": text[:200]},
            )
    except Exception:
        pass


def parse_update(update: dict) -> tuple[str | None, str | None, str | None]:
    """Return (chat_id, command, args)."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None, None, None
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", "")) or None
    text = (msg.get("text") or "").strip()
    if not text.startswith("/"):
        return chat_id, None, text
    parts = text.split(maxsplit=1)
    cmd = parts[0].split("@")[0].lower()
    args = parts[1].strip() if len(parts) > 1 else ""
    return chat_id, cmd, args


def handle_telegram_update(db, update: dict) -> None:
    """Process /start and /watch commands."""
    from app.core.price_alerts import ensure_telegram_link_token, set_favorite_alert
    from app.models.models import Game, User

    # TEMP: discover a channel's numeric chat id for the deals auto-post setup.
    for _k in ("my_chat_member", "channel_post", "chat_member"):
        if _k in update:
            _ch = (update.get(_k) or {}).get("chat", {})
            logger.info(
                "TG_DISCOVER %s chat_id=%s type=%s title=%s username=%s",
                _k, _ch.get("id"), _ch.get("type"), _ch.get("title"), _ch.get("username"),
            )

    chat_id, cmd, args = parse_update(update)
    if not chat_id:
        return

    if cmd == "/start":
        token = args.split()[0] if args else ""
        if not token:
            send_telegram_message(
                chat_id,
                "Cześć! Połącz konto w panelu KupujPL Gry (Ustawienia → Telegram), "
                "potem użyj /start z tokenem z panelu.",
            )
            return
        user = db.query(User).filter(User.telegram_link_token == token).first()
        if not user:
            send_telegram_message(chat_id, "Nieprawidłowy token. Wygeneruj nowy w panelu.")
            return
        user.telegram_chat_id = chat_id
        db.commit()
        send_telegram_message(chat_id, f"Połączono z {user.email}. Użyj /watch slug-gry aby włączyć alert.")
        return

    if cmd == "/watch":
        slug = args.split()[0] if args else ""
        if not slug:
            send_telegram_message(chat_id, "Użycie: /watch slug-gry")
            return
        user = db.query(User).filter(User.telegram_chat_id == chat_id).first()
        if not user:
            send_telegram_message(chat_id, "Najpierw połącz konto: /start TOKEN z panelu.")
            return
        game = db.query(Game).filter(Game.slug == slug).first()
        if not game:
            send_telegram_message(chat_id, f"Nie znaleziono gry: {slug}")
            return
        set_favorite_alert(db, user_id=user.id, game_id=game.id, enabled=True)
        send_telegram_message(chat_id, f"Alert włączony dla: {game.title}")
        return

    if cmd == "/help":
        send_telegram_message(
            chat_id,
            "Komendy:\n/start TOKEN — połącz konto\n/watch slug — alert cenowy\n/help",
        )
