"""Behavioral analytics (funnel instrumentation).

POST /events        — batch-ingest pseudonymous funnel events from the browser
GET  /events/funnel — distinct-session counts per step + conversion ratios

No PII: a random client session id, event name, route, small metadata. These
are REAL product metrics (the funnel), distinct from any AI-simulated testing.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.event import Event
from app.models.user import User
from app.routers.auth import current_user

router = APIRouter(prefix="/events", tags=["events"])

# Canonical funnel order (NOTICE → … → RETURN).
FUNNEL = [
    "session_started",
    "site_viewed",
    "mission_started",
    "mission_submitted",
    "verification_completed",
    "community_opened",
    "push_subscribed",
]

ALLOWED = set(FUNNEL) | {
    "map_engaged",
    "photo_captured",
    "receipt_viewed",
    "notification_opened",
    "share_clicked",
    "identity_viewed",
}


class EventIn(BaseModel):
    session_id: str = Field(max_length=64)
    name: str = Field(max_length=48)
    route: str | None = Field(default=None, max_length=128)
    meta: dict | None = None


class EventBatch(BaseModel):
    events: list[EventIn] = Field(max_length=50)


@router.post("", status_code=202)
async def ingest(
    batch: EventBatch,
    session: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
) -> dict:
    stored = 0
    for e in batch.events:
        if e.name not in ALLOWED:
            continue  # ignore unknown names (keeps the table clean)
        session.add(
            Event(
                session_id=e.session_id[:64],
                name=e.name,
                route=(e.route or "")[:128] or None,
                meta=e.meta,
                user_id=user.id if user else None,
            )
        )
        stored += 1
    await session.commit()
    return {"stored": stored}


@router.get("/funnel")
async def funnel(session: AsyncSession = Depends(get_session)) -> dict:
    """Distinct sessions reaching each funnel step + step-to-step conversion."""
    rows = (
        await session.execute(
            select(Event.name, func.count(func.distinct(Event.session_id))).group_by(
                Event.name
            )
        )
    ).all()
    counts = {name: int(n) for name, n in rows}

    steps = []
    prev: int | None = None
    for name in FUNNEL:
        c = counts.get(name, 0)
        conv = round(100 * c / prev) if prev else None  # vs previous step
        steps.append({"step": name, "sessions": c, "conversion_from_prev_pct": conv})
        prev = c if c else prev

    # A few named ratios (null-safe) for the dashboard / report.
    def ratio(a: str, b: str) -> int | None:
        base = counts.get(b, 0)
        return round(100 * counts.get(a, 0) / base) if base else None

    return {
        "funnel": steps,
        "ratios": {
            "mission_conversion_pct": ratio("mission_started", "site_viewed"),
            "mission_completion_pct": ratio("mission_submitted", "mission_started"),
            "verification_conversion_pct": ratio("verification_completed", "mission_submitted"),
            "community_discovery_pct": ratio("community_opened", "mission_submitted"),
        },
        "counts": counts,
        "note": "Real product funnel (distinct client sessions). Not AI-simulated.",
    }
