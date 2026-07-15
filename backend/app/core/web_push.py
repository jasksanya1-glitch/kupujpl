"""Web Push (PWA) subscriptions and delivery."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import PushSubscription, User

logger = logging.getLogger("web_push")


def vapid_configured() -> bool:
    return bool(os.getenv("VAPID_PRIVATE_KEY", "").strip() and os.getenv("VAPID_PUBLIC_KEY", "").strip())


def get_vapid_public_key() -> str | None:
    key = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    return key or None


def get_vapid_contact() -> str:
    email = os.getenv("VAPID_CONTACT_EMAIL", "kontakt@kupujpl.pl").strip()
    if email.startswith("mailto:"):
        return email
    return f"mailto:{email}"


def upsert_push_subscription(
    db: Session,
    *,
    user_id: int,
    endpoint: str,
    p256dh: str,
    auth_key: str,
    user_agent: str | None = None,
) -> PushSubscription:
    endpoint = endpoint.strip()[:512]
    row = db.query(PushSubscription).filter(PushSubscription.endpoint == endpoint).first()
    if row:
        row.user_id = user_id
        row.p256dh = p256dh
        row.auth_key = auth_key
        row.user_agent = (user_agent or row.user_agent or "")[:240] or None
    else:
        row = PushSubscription(
            user_id=user_id,
            endpoint=endpoint,
            p256dh=p256dh,
            auth_key=auth_key,
            user_agent=(user_agent or "")[:240] or None,
        )
        db.add(row)
    db.commit()
    db.refresh(row)
    return row


def remove_push_subscription(db: Session, *, user_id: int, endpoint: str | None = None) -> int:
    q = db.query(PushSubscription).filter(PushSubscription.user_id == user_id)
    if endpoint:
        q = q.filter(PushSubscription.endpoint == endpoint.strip()[:512])
    count = q.count()
    q.delete(synchronize_session=False)
    db.commit()
    return count


def user_push_status(db: Session, user_id: int) -> dict[str, Any]:
    count = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).count()
    return {
        "supported": True,
        "configured": vapid_configured(),
        "subscribed": count > 0,
        "subscription_count": int(count),
        "vapid_public_key": get_vapid_public_key(),
    }


def send_web_push_to_user(
    db: Session,
    *,
    user_id: int,
    title: str,
    body: str,
    url: str,
    tag: str | None = None,
) -> int:
    if not vapid_configured():
        return 0
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not installed — web push skipped")
        return 0

    subs = db.query(PushSubscription).filter(PushSubscription.user_id == user_id).all()
    if not subs:
        return 0

    payload = json.dumps(
        {
            "title": title[:120],
            "body": body[:240],
            "url": url[:480],
            "tag": (tag or "kupujpl-alert")[:64],
        },
        ensure_ascii=False,
    )
    private_key = os.getenv("VAPID_PRIVATE_KEY", "").strip().replace("\\n", "\n")
    sent = 0
    stale: list[PushSubscription] = []

    for sub in subs:
        subscription_info = {
            "endpoint": sub.endpoint,
            "keys": {"p256dh": sub.p256dh, "auth": sub.auth_key},
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=private_key,
                vapid_claims={"sub": get_vapid_contact()},
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                stale.append(sub)
            else:
                logger.warning("Web push failed user=%s status=%s: %s", user_id, status, exc)
        except Exception as exc:
            logger.warning("Web push failed user=%s: %s", user_id, exc)

    for sub in stale:
        db.delete(sub)
    if stale:
        db.commit()
    return sent
