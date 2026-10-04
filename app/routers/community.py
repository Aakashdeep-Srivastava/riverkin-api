"""Community endpoints (Track 5 — sustained participation, ethical framing).

GET /community/standings            — per-city collective progress, ranked by usefulness
GET /community/challenges[?city=]   — this-period field challenges derived live from sites

Deliberately COLLECTIVE (city / crew), never a per-person points leaderboard
(API CLAUDE.md hard rule + the RiverKin design-psychology model: social proof by
*usefulness*, not vanity). Everything here is computed live from the real OAH
sites and submitted observations — no mock data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.observation import Observation
from app.models.site import Site

router = APIRouter(prefix="/community", tags=["community"])

FRESH_NEED = 0.3  # a site is "fresh" below this need score (matches /metrics)
RAIN_MM = 20.0  # after-the-rain threshold (matches the scheduled job)


class CityStanding(BaseModel):
    city: str
    country: str | None = None
    sites_total: int
    sites_fresh: int
    coverage_pct: int
    gaps_closed: int  # cumulative days-unseen closed by verified checks
    checks_7d: int  # field checks submitted in the last 7 days
    rank: int


class Challenge(BaseModel):
    id: str
    city: str | None
    title: str
    detail: str
    target: int
    progress: int
    kind: str  # after-rain | orphan | coverage


@router.get("/standings", response_model=list[CityStanding])
async def standings(
    session: AsyncSession = Depends(get_session),
) -> list[CityStanding]:
    """Per-city collective progress, most-covered first (usefulness, not vanity)."""
    since = datetime.now(UTC) - timedelta(days=7)
    rows: list[CityStanding] = []
    cities = (
        (await session.execute(select(Site.city, Site.country).distinct()))
        .all()
    )
    for city, country in cities:
        if not city:
            continue
        total = int(
            (await session.execute(
                select(func.count(Site.id)).where(Site.city == city)
            )).scalar() or 0
        )
        fresh = int(
            (await session.execute(
                select(func.count(Site.id)).where(
                    Site.city == city, Site.need_score < FRESH_NEED
                )
            )).scalar() or 0
        )
        gaps = int(
            (await session.execute(
                select(func.coalesce(func.sum(Observation.gap_days_closed), 0))
                .join(Site, Observation.site_id == Site.id)
                .where(Site.city == city)
            )).scalar() or 0
        )
        checks = int(
            (await session.execute(
                select(func.count(Observation.id))
                .join(Site, Observation.site_id == Site.id)
                .where(Site.city == city, Observation.created_at >= since)
            )).scalar() or 0
        )
        rows.append(
            CityStanding(
                city=city,
                country=country,
                sites_total=total,
                sites_fresh=fresh,
                coverage_pct=round(100 * fresh / total) if total else 0,
                gaps_closed=gaps,
                checks_7d=checks,
                rank=0,
            )
        )
    rows.sort(key=lambda r: (r.coverage_pct, r.gaps_closed), reverse=True)
    for i, r in enumerate(rows, start=1):
        r.rank = i
    return rows


@router.get("/challenges", response_model=list[Challenge])
async def challenges(
    city: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[Challenge]:
    """This-period field challenges, derived live from sites needing a look.

    No fake urgency: every target is a real count of sites in that state right now.
    """
    base = select(Site)
    if city:
        base = base.where(Site.city == city)
    sites = (await session.execute(base)).scalars().all()
    if not sites:
        return []

    now = datetime.now(UTC)

    def days_unseen(s: Site) -> int:
        if s.last_verified_at is None:
            return 999
        return max(0, (now - s.last_verified_at).days)

    after_rain = [s for s in sites if (s.rain_48h_mm or 0) >= RAIN_MM and days_unseen(s) >= 3]
    orphans = [s for s in sites if days_unseen(s) >= 21]
    needing = [s for s in sites if (s.need_score or 0) >= FRESH_NEED]

    scope = city or "every city"
    out: list[Challenge] = []
    if after_rain:
        out.append(Challenge(
            id=f"after-rain-{city or 'all'}",
            city=city,
            title="After the rain",
            detail=f"{len(after_rain)} sites in {scope} had heavy rain and are due a check.",
            target=len(after_rain), progress=0, kind="after-rain",
        ))
    if orphans:
        out.append(Challenge(
            id=f"orphan-{city or 'all'}",
            city=city,
            title="Nobody's watching",
            detail=f"{len(orphans)} sites in {scope} haven't been seen in 3+ weeks.",
            target=len(orphans), progress=0, kind="orphan",
        ))
    if needing:
        out.append(Challenge(
            id=f"coverage-{city or 'all'}",
            city=city,
            title="Lift the coverage",
            detail=f"{len(needing)} sites in {scope} need attention to turn the map green.",
            target=len(needing), progress=0, kind="coverage",
        ))
    return out
