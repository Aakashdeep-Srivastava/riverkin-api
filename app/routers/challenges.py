"""Community challenge endpoints (Track 5 growth loop) — real, DB-backed.

GET  /challenges[?status=]        — campaign challenges (live joined counts)
GET  /challenges/{id}             — one challenge
POST /challenges/{id}/join        — join as a participant (guest or user), process referral
GET  /community/profile?key=      — a participant's COMMUNITY ledger (credits, missions, …)
POST /referrals                   — attach a referral (from a /join/[code] link)

Participation is pseudonymous (``key`` = guest id ``RK-XXXX`` or a user email).
Community credits reward participation + referrals; they are computed from the
DB and NEVER affect a check's scientific trust/verification (two separate
ledgers, by design).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.challenge import Challenge, ChallengeParticipant, Referral

router = APIRouter(tags=["challenges"])

# Community-credit weights (participation, not vanity; never touches science).
JOIN_FRACTION = 0.25
REPORT_CREDIT = 20
REFERRAL_CREDIT = 50


class ChallengeOut(BaseModel):
    id: str
    title: str
    city: str | None
    kind: str
    meta: str
    window: str
    status: str
    days_left: int
    sites: int
    blurb: str
    credit: int
    featured: bool
    joined: int  # base_joined + real participants


class CommunityProfile(BaseModel):
    key: str
    credits: int
    missions: int  # challenges joined
    checks: int  # reports/observations submitted via challenges
    rivers_helped: int  # distinct cities
    referrals: int  # friends who joined via your link
    joined_ids: list[str] = []  # challenge ids this key has joined


class JoinBody(BaseModel):
    key: str = Field(min_length=3, max_length=64)
    referrer: str | None = Field(default=None, max_length=64)


class JoinResult(BaseModel):
    challenge: ChallengeOut
    profile: CommunityProfile


class ReferralBody(BaseModel):
    referrer: str = Field(min_length=3, max_length=64)
    referred: str = Field(min_length=3, max_length=64)


async def _participant_counts(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(
                ChallengeParticipant.challenge_id,
                func.count(ChallengeParticipant.id),
            ).group_by(ChallengeParticipant.challenge_id)
        )
    ).all()
    return {cid: n for cid, n in rows}


def _to_out(c: Challenge, extra_joined: int) -> ChallengeOut:
    return ChallengeOut(
        id=c.id,
        title=c.title,
        city=c.city,
        kind=c.kind,
        meta=c.meta,
        window=c.window,
        status=c.status,
        days_left=c.days_left,
        sites=c.sites,
        blurb=c.blurb,
        credit=c.credit,
        featured=c.featured,
        joined=c.base_joined + extra_joined,
    )


@router.get("/challenges", response_model=list[ChallengeOut])
async def list_challenges(
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[ChallengeOut]:
    stmt = select(Challenge).order_by(Challenge.sort)
    if status:
        stmt = stmt.where(Challenge.status == status)
    challenges = (await session.execute(stmt)).scalars().all()
    counts = await _participant_counts(session)
    return [_to_out(c, counts.get(c.id, 0)) for c in challenges]


@router.get("/challenges/{challenge_id}", response_model=ChallengeOut)
async def get_challenge(
    challenge_id: str, session: AsyncSession = Depends(get_session)
) -> ChallengeOut:
    c = await session.get(Challenge, challenge_id)
    if not c:
        raise HTTPException(status_code=404, detail="challenge not found")
    counts = await _participant_counts(session)
    return _to_out(c, counts.get(c.id, 0))


async def _profile(session: AsyncSession, key: str) -> CommunityProfile:
    parts = (
        await session.execute(
            select(ChallengeParticipant, Challenge)
            .join(Challenge, Challenge.id == ChallengeParticipant.challenge_id)
            .where(ChallengeParticipant.participant_key == key)
        )
    ).all()

    credits = 0
    checks = 0
    cities: set[str] = set()
    joined_ids: list[str] = []
    for part, chal in parts:
        credits += round(chal.credit * JOIN_FRACTION) + part.reports_submitted * REPORT_CREDIT
        checks += part.reports_submitted
        joined_ids.append(chal.id)
        if chal.city:
            cities.add(chal.city)

    referrals = (
        await session.execute(
            select(func.count(Referral.id)).where(
                Referral.referrer_key == key, Referral.credited.is_(True)
            )
        )
    ).scalar_one()
    credits += referrals * REFERRAL_CREDIT

    return CommunityProfile(
        key=key,
        credits=credits,
        missions=len(parts),
        checks=checks,
        rivers_helped=len(cities),
        referrals=referrals,
        joined_ids=joined_ids,
    )


@router.get("/community/profile", response_model=CommunityProfile)
async def community_profile(
    key: str = Query(min_length=3, max_length=64),
    session: AsyncSession = Depends(get_session),
) -> CommunityProfile:
    return await _profile(session, key)


async def _attach_referral(
    session: AsyncSession, referrer: str, referred: str, *, credited: bool
) -> None:
    if not referrer or referrer == referred:
        return
    existing = (
        await session.execute(
            select(Referral).where(Referral.referred_key == referred)
        )
    ).scalar_one_or_none()
    if existing:
        if credited and not existing.credited:
            existing.credited = True
        return
    session.add(
        Referral(referrer_key=referrer, referred_key=referred, credited=credited)
    )


@router.post("/referrals", response_model=CommunityProfile)
async def attach_referral(
    body: ReferralBody, session: AsyncSession = Depends(get_session)
) -> CommunityProfile:
    # Attached on landing (not yet credited — the referred must join a challenge).
    await _attach_referral(session, body.referrer, body.referred, credited=False)
    await session.commit()
    return await _profile(session, body.referred)


@router.post("/challenges/{challenge_id}/join", response_model=JoinResult)
async def join_challenge(
    challenge_id: str,
    body: JoinBody,
    session: AsyncSession = Depends(get_session),
) -> JoinResult:
    c = await session.get(Challenge, challenge_id)
    if not c:
        raise HTTPException(status_code=404, detail="challenge not found")

    # Idempotent join.
    stmt = (
        insert(ChallengeParticipant)
        .values(challenge_id=challenge_id, participant_key=body.key)
        .on_conflict_do_nothing(index_elements=["challenge_id", "participant_key"])
    )
    await session.execute(stmt)

    # Credit the referrer: either an explicit referrer in the body, or an
    # already-attached (un-credited) referral for this key. Joining a challenge
    # is the "meaningful action" that credits the inviter.
    if body.referrer:
        await _attach_referral(session, body.referrer, body.key, credited=True)
    else:
        pending = (
            await session.execute(
                select(Referral).where(
                    Referral.referred_key == body.key, Referral.credited.is_(False)
                )
            )
        ).scalar_one_or_none()
        if pending:
            pending.credited = True

    await session.commit()

    counts = await _participant_counts(session)
    return JoinResult(
        challenge=_to_out(c, counts.get(c.id, 0)),
        profile=await _profile(session, body.key),
    )
