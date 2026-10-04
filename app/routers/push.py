"""Web Push subscription endpoints.

GET  /push/vapid-public    — the browser applicationServerKey (empty = disabled)
POST /push/subscribe       — store a browser PushSubscription (idempotent)
POST /push/unsubscribe     — remove one by endpoint

Pseudonymous: we store only the push endpoint + keys (+ optional user link). The
scheduled job uses these to send after-rain / coverage nudges (app/push.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models.push import PushSubscription
from app.models.user import User
from app.routers.auth import current_user

router = APIRouter(prefix="/push", tags=["push"])


class SubKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeIn(BaseModel):
    endpoint: str
    keys: SubKeys


class EndpointIn(BaseModel):
    endpoint: str


@router.get("/vapid-public")
async def vapid_public() -> dict:
    """The public VAPID key for the browser (empty string → push is disabled)."""
    return {"key": settings.VAPID_PUBLIC}


@router.post("/subscribe", status_code=201)
async def subscribe(
    payload: SubscribeIn,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
) -> dict:
    stmt = insert(PushSubscription).values(
        endpoint=payload.endpoint,
        p256dh=payload.keys.p256dh,
        auth=payload.keys.auth,
        user_id=user.id if user else None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["endpoint"],
        set_={"p256dh": payload.keys.p256dh, "auth": payload.keys.auth},
    )
    await session.execute(stmt)
    await session.commit()
    return {"subscribed": True}


@router.post("/unsubscribe")
async def unsubscribe(
    payload: EndpointIn, session: AsyncSession = Depends(get_session)
) -> dict:
    await session.execute(
        delete(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    await session.commit()
    return {"unsubscribed": True}
