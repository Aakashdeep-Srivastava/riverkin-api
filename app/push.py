"""Web Push sending (VAPID) — the Track-5 reactivation trigger.

Sends real, honest nudges (after-rain / coverage) to subscribed browsers. Pure
of business logic beyond delivery; callers decide WHAT to send. Expired/invalid
subscriptions (HTTP 404/410) are pruned. No-op when VAPID isn't configured.
"""

from __future__ import annotations

import base64
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.push import PushSubscription

logger = logging.getLogger("app.push")


def _private_pem() -> str | None:
    if not settings.VAPID_PRIVATE_B64:
        return None
    try:
        return base64.b64decode(settings.VAPID_PRIVATE_B64).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        logger.warning("VAPID_PRIVATE_B64 is not valid base64 PEM")
        return None


def enabled() -> bool:
    return bool(settings.VAPID_PUBLIC and _private_pem())


def _send_one(sub: PushSubscription, payload: dict) -> bool:
    """Send one push. Returns False if the subscription is gone (prune it)."""
    pem = _private_pem()
    if pem is None:
        return True
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=pem,
            vapid_claims={"sub": settings.VAPID_SUBJECT},
            ttl=86400,
        )
        return True
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            return False  # subscription expired → caller prunes
        logger.warning("web push failed (%s): %s", status, str(exc)[:120])
        return True
    except Exception as exc:  # never let a bad sub break the job
        logger.warning("web push error: %s", str(exc)[:120])
        return True


async def broadcast(session: AsyncSession, *, title: str, body: str, url: str = "/") -> int:
    """Send a nudge to every subscription; prune the dead ones. Returns #sent."""
    if not enabled():
        return 0
    subs = (await session.execute(select(PushSubscription))).scalars().all()
    payload = {"title": title, "body": body, "url": url}
    sent = 0
    dead: list[str] = []
    for sub in subs:
        if _send_one(sub, payload):
            sent += 1
        else:
            dead.append(sub.endpoint)
    if dead:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint.in_(dead))
        )
        await session.commit()
    logger.info("web push: sent %d, pruned %d", sent, len(dead))
    return sent
