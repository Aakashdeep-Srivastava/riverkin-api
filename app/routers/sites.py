"""Sites endpoints (Perfect 6 #1).

GET /sites                 — all OAH sites with live need score + attention
GET /sites/{oah_code}      — a single site
GET /sites/{oah_code}/timeline — recent checks / rain (minimal for now)

Backed by the seeded 106-site OAH table (see app/seed.py). ``need_score`` and
``attention`` come from app/scoring.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import scoring
from app.db import get_session
from app.models.site import Site
from app.schemas import SiteOut, SiteTimelineOut

router = APIRouter(prefix="/sites", tags=["sites"])

ORPHAN_DAYS = 999


def _days_unseen(site: Site) -> int:
    if site.last_verified_at is None:
        return ORPHAN_DAYS
    delta = datetime.now(UTC) - site.last_verified_at
    return max(0, delta.days)


def _to_out(site: Site) -> SiteOut:
    days = _days_unseen(site)
    need = site.need_score if site.need_score is not None else 0.0
    return SiteOut(
        id=site.external_id or str(site.id),
        name=site.name,
        waterbody=site.waterbody,
        city=site.city,
        country=site.country,
        lat=site.lat,
        lng=site.lng,
        days_unseen=days,
        rain_48h_mm=site.rain_48h_mm or 0.0,
        need_score=round(need, 4),
        attention=scoring.attention_level(
            need, days_since_check=float(days), expert_flag_open=site.expert_flag_open
        ),
        color=scoring.need_color(
            need, expert_flag_open=site.expert_flag_open, days_since_check=float(days)
        ),
        simulated=site.simulated,
    )


@router.get("", response_model=list[SiteOut])
async def list_sites(
    city: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[SiteOut]:
    """All sites, most-urgent first. Optional ``city`` filter."""
    stmt = select(Site)
    if city:
        stmt = stmt.where(Site.city == city)
    rows = (await session.execute(stmt)).scalars().all()
    out = [_to_out(s) for s in rows]
    out.sort(key=lambda s: s.need_score, reverse=True)
    return out


@router.get("/{oah_code}", response_model=SiteOut)
async def get_site(
    oah_code: str,
    session: AsyncSession = Depends(get_session),
) -> SiteOut:
    stmt = select(Site).where(Site.external_id == oah_code)
    site = (await session.execute(stmt)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")
    return _to_out(site)


@router.get("/{oah_code}/timeline", response_model=SiteTimelineOut)
async def site_timeline(
    oah_code: str,
    session: AsyncSession = Depends(get_session),
) -> SiteTimelineOut:
    """Recent checks + rain events for a site.

    TODO(PRD): real check/rain/verification entries + field-diff "What changed?".
    For now returns the last verified check so the C2 preview has something real.
    """
    stmt = select(Site).where(Site.external_id == oah_code)
    site = (await session.execute(stmt)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")
    entries = []
    if site.last_verified_at is not None:
        entries.append(
            {
                "kind": "check",
                "label": "Last verified check",
                "at": site.last_verified_at.isoformat(),
            }
        )
    return SiteTimelineOut(site_id=oah_code, entries=entries, simulated=site.simulated)
