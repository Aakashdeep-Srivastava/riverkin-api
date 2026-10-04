"""In-app notifications (Track 5 — engagement & return).

GET /notifications[?city=]  — a small feed of warm, honest nudges derived LIVE
from real state: checks that got community-verified, sites that need a look
after rain, rivers nobody has watched in weeks, and coverage milestones.

Design rules (RiverKin design-psychology model): every nudge is a REAL count or
event — no fake urgency, no streak guilt. Copy is short and kind so a child or
an adult reads it the same way. The frontend adds the personal ones (identity
progress, "your check was verified") from on-device history.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.observation import Observation
from app.models.site import Site

router = APIRouter(prefix="/notifications", tags=["notifications"])

FRESH_NEED = 0.3
RAIN_MM = 20.0


class Notification(BaseModel):
    id: str
    kind: str  # verified | after-rain | orphan | coverage
    icon: str  # frontend maps to an icon
    title: str
    body: str
    href: str
    accent: str  # css colour token/hex
    at: str  # ISO8601


@router.get("", response_model=list[Notification])
async def notifications(
    city: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[Notification]:
    now = datetime.now(UTC)
    out: list[Notification] = []

    # 1) Recent community-verified / final checks — celebrate real wins.
    verified_rows = (
        await session.execute(
            select(Observation, Site.name)
            .join(Site, Observation.site_id == Site.id)
            .where(Observation.status.in_(("community-verified", "final")))
            .order_by(Observation.updated_at.desc())
            .limit(5)
        )
    ).all()
    for obs, site_name in verified_rows:
        closed = obs.gap_days_closed or 0
        body = (
            f"A check on {site_name} was confirmed by the community"
            + (f" — a {closed}-day gap closed." if closed else ".")
        )
        out.append(Notification(
            id=f"verified-{obs.id}",
            kind="verified",
            icon="badge-check",
            title="A check was verified! 🎉",
            body=body,
            href=f"/receipt/{obs.id}",
            accent="#2FA36B",
            at=(obs.updated_at or now).isoformat(),
        ))

    # Site state for the nudges below.
    base = select(Site)
    if city:
        base = base.where(Site.city == city)
    sites = (await session.execute(base)).scalars().all()

    def days_unseen(s: Site) -> int:
        if s.last_verified_at is None:
            return 999
        return max(0, (now - s.last_verified_at).days)

    # 2) After the rain — real count of rained-on, due sites.
    after_rain = [s for s in sites if (s.rain_48h_mm or 0) >= RAIN_MM and days_unseen(s) >= 3]
    if after_rain:
        scope = city or "five cities"
        out.append(Notification(
            id=f"after-rain-{city or 'all'}",
            kind="after-rain",
            icon="cloud-rain",
            title="After the rain 🌧️",
            body=f"{len(after_rain)} sites in {scope} had heavy rain and are due a look.",
            href="/missions" + (f"?city={city}" if city else ""),
            accent="#12A4D9",
            at=now.isoformat(),
        ))

    # 3) Nobody's watching — the single most-overlooked river.
    orphans = sorted(
        [s for s in sites if days_unseen(s) >= 21], key=days_unseen, reverse=True
    )
    if orphans:
        top = orphans[0]
        out.append(Notification(
            id=f"orphan-{top.external_id}",
            kind="orphan",
            icon="eye-off",
            title="A river is waiting 👀",
            body=f"Nobody has checked {top.name} in {days_unseen(top)} days. Be the one who does.",
            href=f"/sites/{top.external_id}",
            accent="#F2A93B",
            at=now.isoformat(),
        ))

    # 4) Coverage milestone — a shared, honest goal.
    if sites:
        fresh = sum(1 for s in sites if (s.need_score or 0) < FRESH_NEED)
        pct = round(100 * fresh / len(sites))
        scope = city or "Europe's streams"
        out.append(Notification(
            id=f"coverage-{city or 'all'}",
            kind="coverage",
            icon="trending-up",
            title="Keep the map green 💚",
            body=f"{pct}% of {scope} are fresh right now. Every check lifts it.",
            href="/community",
            accent="#0052FF",
            at=now.isoformat(),
        ))

    return out
