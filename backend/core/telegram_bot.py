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
    reply_markup: dict | None = None,
    message_thread_id: int | None = None,
) -> int | None:
    """Send a message. Returns Telegram message_id on success, else None."""
    if not TELEGRAM_API:
        logger.debug("Telegram bot not configured")
        return None
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    if message_thread_id is not None:
        payload["message_thread_id"] = int(message_thread_id)
    try:
        with httpx.Client(timeout=20) as client:
            r = client.post(f"{TELEGRAM_API}/sendMessage", json=payload)
            r.raise_for_status()
            data = r.json() if r.content else {}
            mid = (data.get("result") or {}).get("message_id")
            return int(mid) if mid is not None else None
    except Exception as exc:
        detail = ""
        resp = getattr(exc, "response", None)
        if resp is not None:
            try:
                detail = resp.text[:300]
            except Exception:
                pass
        logger.warning("sendMessage failed: %s %s", exc, detail)
        return None


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
    """Process /start and /watch commands + site-chat replies."""
    from app.core.price_alerts import ensure_telegram_link_token, set_favorite_alert
    from app.core.site_chat import (
        try_handle_callback,
        try_handle_odp_command,
        try_handle_telegram_reply,
    )
    from app.models.models import Game, User

    # TEMP: discover a channel's numeric chat id for the deals auto-post setup.
    for _k in ("my_chat_member", "channel_post", "chat_member"):
        if _k in update:
            _ch = (update.get(_k) or {}).get("chat", {})
            logger.info(
                "TG_DISCOVER %s chat_id=%s type=%s title=%s username=%s",
                _k, _ch.get("id"), _ch.get("type"), _ch.get("title"), _ch.get("username"),
            )

    # Inline buttons (Odpowiedz / Anuluj)
    try:
        if try_handle_callback(db, update):
            return
    except Exception as exc:
        logger.warning("site chat callback failed: %s", exc)

    # Owner reply / pending text reply → publish on website
    try:
        if try_handle_telegram_reply(db, update):
            return
    except Exception as exc:
        logger.warning("site chat reply handler failed: %s", exc)

    chat_id, cmd, args = parse_update(update)
    if not chat_id:
        return

    if cmd in ("/odp", "/czat"):
        try:
            if try_handle_odp_command(db, chat_id, args):
                return
        except Exception as exc:
            logger.warning("site chat /odp failed: %s", exc)
        return

    if cmd in ("/cancel", "/anuluj"):
        return

    if cmd == "/start":
        token = args.split()[0] if args else ""
        if not token:
            from app.core.site_owner import SITE_OWNER_EMAIL

            if SITE_OWNER_EMAIL:
                owner = db.query(User).filter(User.email.ilike(SITE_OWNER_EMAIL)).first()
                if owner and not owner.telegram_chat_id:
                    owner.telegram_chat_id = chat_id
                    db.commit()
                    send_telegram_message(
                        chat_id,
                        "Połączono Telegram do powiadomień Kup (kliknięcia w sklep). "
                        "Pełne alerty cen: panel → Ustawienia → /start TOKEN.",
                    )
                    return
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
            "Komendy:\n/start TOKEN — połącz konto\n/watch slug — alert cenowy\n/help\n"
            "Czat strony:\n• przycisk «Odpowiedz» pod powiadomieniem\n"
            "• lub reply / /odp ID treść",
        )
