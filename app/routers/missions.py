"""Missions endpoints (FR11).

GET /missions              — suggested field missions, most-urgent first (?city=)
GET /missions/{oah_code}   — the C3 mission brief for one site

Missions are derived live from the seeded OAH sites using the same need score and
attention bands as GET /sites (see app/scoring.py) plus the mission typing rules
in app/missions.py. No mission is stored; each reflects the site's current state.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import missions, scoring
from app.db import get_session
from app.models.site import Site
from app.schemas import MissionBriefOut, MissionOut

router = APIRouter(prefix="/missions", tags=["missions"])

ORPHAN_DAYS = 999


def _days_unseen(site: Site) -> int:
    if site.last_verified_at is None:
        return ORPHAN_DAYS
    delta = datetime.now(UTC) - site.last_verified_at
    return max(0, delta.days)


def _attention(site: Site, days: int) -> tuple[str, str, float]:
    need = site.need_score if site.need_score is not None else 0.0
    attention = scoring.attention_level(
        need, days_since_check=float(days), expert_flag_open=site.expert_flag_open
    )
    color = scoring.need_color(
        need, expert_flag_open=site.expert_flag_open, days_since_check=float(days)
    )
    return attention, color, round(need, 4)


def _to_mission(site: Site) -> MissionOut:
    days = _days_unseen(site)
    attention, color, need = _attention(site, days)
    kind = missions.classify(
        days_unseen=days,
        rain_48h_mm=site.rain_48h_mm or 0.0,
        cadence_days=site.cadence_days,
        expert_flag_open=site.expert_flag_open,
    )
    sid = site.external_id or str(site.id)
    return MissionOut(
        id=f"mission-{sid}",
        site_id=sid,
        site_name=site.name,
        waterbody=site.waterbody,
        city=site.city,
        title=kind.title,
        summary=kind.summary,
        attention=attention,
        color=color,
        need_score=need,
        days_unseen=days,
        simulated=site.simulated,
    )


def _to_brief(site: Site) -> MissionBriefOut:
    days = _days_unseen(site)
    attention, color, need = _attention(site, days)
    rain = site.rain_48h_mm or 0.0
    kind = missions.classify(
        days_unseen=days,
        rain_48h_mm=rain,
        cadence_days=site.cadence_days,
        expert_flag_open=site.expert_flag_open,
    )
    sid = site.external_id or str(site.id)
    return MissionBriefOut(
        id=f"mission-{sid}",
        site_id=sid,
        site_name=site.name,
        waterbody=site.waterbody,
        city=site.city,
        name=kind.title,
        window_label=kind.window_label,
        est_minutes=missions.EST_MINUTES,
        safety_line=missions.SAFETY_LINE,
        steps=list(missions.STEPS),
        attention=attention,
        color=color,
        need_score=need,
        days_unseen=days,
        rain_48h_mm=rain,
        simulated=site.simulated,
    )


@router.get("", response_model=list[MissionOut])
async def list_missions(
    city: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[MissionOut]:
    """Suggested field missions, most-urgent first. Optional ``city`` filter.

    Only sites that actually warrant a look are returned (open flag, fresh rain,
    past cadence, or any non-``ok`` attention band).
    """
    stmt = select(Site)
    if city:
        stmt = stmt.where(Site.city == city)
    rows = (await session.execute(stmt)).scalars().all()

    out: list[MissionOut] = []
    for site in rows:
        days = _days_unseen(site)
        attention, _, _ = _attention(site, days)
        if missions.warrants_mission(
            attention=attention,
            days_unseen=days,
            rain_48h_mm=site.rain_48h_mm or 0.0,
            cadence_days=site.cadence_days,
            expert_flag_open=site.expert_flag_open,
        ):
            out.append(_to_mission(site))

    out.sort(key=lambda m: m.need_score, reverse=True)
    return out


@router.get("/{oah_code}", response_model=MissionBriefOut)
async def get_mission_brief(
    oah_code: str,
    session: AsyncSession = Depends(get_session),
) -> MissionBriefOut:
    """The C3 mission brief for a single site, derived from its current state."""
    stmt = select(Site).where(Site.external_id == oah_code)
    site = (await session.execute(stmt)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")
    return _to_brief(site)
