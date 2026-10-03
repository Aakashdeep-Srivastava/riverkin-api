"""Crew endpoints (later layer: L2 Crew Lead setup + L1 Crew view).

POST /crews                    — create a crew (Crew Lead)
POST /crews/{id}/members       — add a pseudonymous member handle
POST /crews/{id}/adoptions     — adopt a site (max 3)
POST /crews/{id}/checkins      — Crew Lead field-safety check-in (90-min window)
GET  /crews/{id}               — crew view: members, adopted sites, coverage, streak

No personal data about members is stored (PRD role model). Adults-only accounts
and full RBAC are out of scope for the hackathon MVP; these endpoints are open so
the demo flows work.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import scoring
from app.db import get_session
from app.models.crew import Adoption, Checkin, Crew, CrewMember
from app.models.site import Site

router = APIRouter(prefix="/crews", tags=["crews"])

MAX_ADOPTIONS = 3
CHECKIN_MINUTES = 90


class CrewIn(BaseModel):
    name: str
    city: str | None = None
    is_minor_crew: bool = False


class MemberIn(BaseModel):
    handle: str
    role_this_week: str | None = None


class AdoptionIn(BaseModel):
    site_code: str


class CrewCreated(BaseModel):
    id: int
    name: str


class MemberOut(BaseModel):
    id: int
    handle: str
    role_this_week: str | None


class AdoptedSiteOut(BaseModel):
    site_code: str
    name: str
    days_unseen: int
    attention: str
    fresh: bool


class CrewView(BaseModel):
    id: int
    name: str
    city: str | None
    is_minor_crew: bool
    members: list[MemberOut]
    adopted: list[AdoptedSiteOut]
    coverage_pct: int
    streak_windows: int
    checkin_active: bool
    simulated: bool = True


def _days_unseen(site: Site) -> int:
    if site.last_verified_at is None:
        return 999
    return max(0, (datetime.now(UTC) - site.last_verified_at).days)


async def _get_crew(session: AsyncSession, crew_id: int) -> Crew:
    crew = await session.get(Crew, crew_id)
    if crew is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="crew not found")
    return crew


@router.post("", response_model=CrewCreated, status_code=status.HTTP_201_CREATED)
async def create_crew(payload: CrewIn, session: AsyncSession = Depends(get_session)) -> CrewCreated:
    crew = Crew(name=payload.name, city=payload.city, is_minor_crew=payload.is_minor_crew)
    session.add(crew)
    await session.commit()
    await session.refresh(crew)
    return CrewCreated(id=crew.id, name=crew.name)


@router.post("/{crew_id}/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
async def add_member(
    crew_id: int, payload: MemberIn, session: AsyncSession = Depends(get_session)
) -> MemberOut:
    await _get_crew(session, crew_id)
    member = CrewMember(
        crew_id=crew_id, handle=payload.handle, role_this_week=payload.role_this_week
    )
    session.add(member)
    await session.commit()
    await session.refresh(member)
    return MemberOut(id=member.id, handle=member.handle, role_this_week=member.role_this_week)


@router.post("/{crew_id}/adoptions", status_code=status.HTTP_201_CREATED)
async def adopt_site(
    crew_id: int, payload: AdoptionIn, session: AsyncSession = Depends(get_session)
) -> dict:
    await _get_crew(session, crew_id)
    count = int(
        (
            await session.execute(
                select(func.count(Adoption.id)).where(Adoption.crew_id == crew_id)
            )
        ).scalar()
        or 0
    )
    if count >= MAX_ADOPTIONS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"a crew may adopt at most {MAX_ADOPTIONS} sites",
        )
    site = (
        await session.execute(select(Site).where(Site.external_id == payload.site_code))
    ).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")
    session.add(Adoption(crew_id=crew_id, site_id=site.id))
    await session.commit()
    return {"adopted": True, "site_code": payload.site_code, "name": site.name}


@router.post("/{crew_id}/checkins", status_code=status.HTTP_201_CREATED)
async def checkin(crew_id: int, session: AsyncSession = Depends(get_session)) -> dict:
    await _get_crew(session, crew_id)
    now = datetime.now(UTC)
    session.add(Checkin(crew_id=crew_id, expires_at=now + timedelta(minutes=CHECKIN_MINUTES)))
    await session.commit()
    return {"checked_in": True, "expires_in_minutes": CHECKIN_MINUTES}


@router.get("/{crew_id}", response_model=CrewView)
async def get_crew(crew_id: int, session: AsyncSession = Depends(get_session)) -> CrewView:
    crew = await _get_crew(session, crew_id)

    members = (
        await session.execute(select(CrewMember).where(CrewMember.crew_id == crew_id))
    ).scalars().all()

    adoptions = (
        await session.execute(
            select(Site)
            .join(Adoption, Adoption.site_id == Site.id)
            .where(Adoption.crew_id == crew_id)
        )
    ).scalars().all()

    adopted_out: list[AdoptedSiteOut] = []
    fresh_count = 0
    for site in adoptions:
        days = _days_unseen(site)
        need = site.need_score or 0.0
        is_fresh = need < 0.3
        fresh_count += 1 if is_fresh else 0
        adopted_out.append(
            AdoptedSiteOut(
                site_code=site.external_id or str(site.id),
                name=site.name,
                days_unseen=days,
                attention=scoring.attention_level(
                    need, days_since_check=float(days), expert_flag_open=site.expert_flag_open
                ),
                fresh=is_fresh,
            )
        )

    coverage = round(100 * fresh_count / len(adopted_out)) if adopted_out else 0

    active = int(
        (
            await session.execute(
                select(func.count(Checkin.id))
                .where(Checkin.crew_id == crew_id)
                .where(Checkin.expires_at > datetime.now(UTC))
            )
        ).scalar()
        or 0
    )

    return CrewView(
        id=crew.id,
        name=crew.name,
        city=crew.city,
        is_minor_crew=crew.is_minor_crew,
        members=[
            MemberOut(id=m.id, handle=m.handle, role_this_week=m.role_this_week) for m in members
        ],
        adopted=adopted_out,
        coverage_pct=coverage,
        streak_windows=crew.streak_windows,
        checkin_active=active > 0,
    )
