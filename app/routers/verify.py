"""Verify-round endpoints (Perfect 6 #4).

GET  /verify/next?n=5&voter_id=   — next items to verify (incl. hidden gold)
POST /verify/{item_id}/vote       — cast a verification vote

The AI only *asks* (the question + a weak prior); humans decide by voting
(CLAUDE.md hard rule). Gold items are injected invisibly (1 in 5) and never
flagged to the verifier. Each vote recomputes observation trust + state.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.experiment import assign_arm
from app.models.observation import Observation
from app.models.site import Site
from app.models.user import User
from app.models.verify import VerifyItem, Vote
from app.schemas import (
    VerifyCard,
    VerifyCountOut,
    VerifyNextOut,
    VerifyPendingItem,
    VerifyPendingOut,
    VoteIn,
    VoteResult,
)
from app.services import recompute_trust

router = APIRouter(prefix="/verify", tags=["verify"])

VALID_ANSWERS = {"yes", "no", "cant_tell"}


@router.get("/next", response_model=VerifyNextOut)
async def next_verify_items(
    n: int = Query(default=5, ge=1, le=20),
    voter_id: str = Query(default="demo-keeper"),
    observation_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> VerifyNextOut:
    """Return the next verify cards for this voter.

    Skips items the voter already voted on and items whose observation is no
    longer open. Gold items are included but never marked as gold in the payload.
    When ``observation_id`` is given (deep-link from a pending-verification
    notification), only that check's cards are returned, so tapping a specific
    submission verifies exactly that one.
    """
    already = select(Vote.verify_item_id).where(Vote.voter_id == voter_id)
    stmt = (
        select(VerifyItem, Observation, Site)
        .join(Observation, VerifyItem.observation_id == Observation.id)
        .join(Site, Observation.site_id == Site.id, isouter=True)
        .where(VerifyItem.resolved.is_(False))
        .where(Observation.status.in_(("in_verify", "pending", "expert")))
        .where(VerifyItem.id.not_in(already))
    )
    if observation_id is not None:
        stmt = stmt.where(VerifyItem.observation_id == observation_id)
    stmt = stmt.order_by(VerifyItem.created_at.asc()).limit(n)
    rows = (await session.execute(stmt)).all()
    cards: list[VerifyCard] = []
    for item, obs, site in rows:
        # AI-assist lift experiment: the control arm is a human-only decision, so
        # withhold the AI box. Assignment is stable per (voter, item).
        arm = assign_arm(voter_id, item.id)
        # The actual evidence to judge: the processed photo served by the
        # observations router. None when the check had no photo.
        photo_url = (
            f"/api/v1/observations/{obs.id}/photo" if obs is not None and obs.photo_path else None
        )
        cards.append(
            VerifyCard(
                item_id=item.id,
                observation_id=item.observation_id,
                site_name=(site.name if site is not None else "A monitored stream"),
                field_code=item.field_code,
                question=item.question,
                ai_box=None if arm == "control" else item.ai_box,
                photo_url=photo_url,
                arm=arm,
            )
        )
    return VerifyNextOut(cards=cards, simulated=len(cards) == 0)


@router.get("/count", response_model=VerifyCountOut)
async def verify_count(
    voter_id: str = Query(default="demo-keeper"),
    session: AsyncSession = Depends(get_session),
) -> VerifyCountOut:
    """Count the checks (observations) still awaiting this voter's verification.

    Same filter as ``/next`` — open verify items on still-open observations the
    voter hasn't voted on — but counts distinct observations, not cards, so the
    number reads as 'N checks need your eyes'.
    """
    already = select(Vote.verify_item_id).where(Vote.voter_id == voter_id)
    stmt = (
        select(func.count(func.distinct(VerifyItem.observation_id)))
        .select_from(VerifyItem)
        .join(Observation, VerifyItem.observation_id == Observation.id)
        .where(VerifyItem.resolved.is_(False))
        .where(Observation.status.in_(("in_verify", "pending", "expert")))
        .where(VerifyItem.id.not_in(already))
    )
    count = (await session.execute(stmt)).scalar() or 0
    return VerifyCountOut(count=int(count))


@router.get("/pending", response_model=VerifyPendingOut)
async def pending_verifications(
    n: int = Query(default=6, ge=1, le=20),
    session: AsyncSession = Depends(get_session),
) -> VerifyPendingOut:
    """Recent submissions awaiting peer verification, with their photo and who
    submitted them — the notification feed renders these as tappable cards.

    Only checks that carry a photo are returned (so each card has a thumbnail).
    The submitter is the Keeper's display name, or "Guest" for anonymous checks.
    """
    stmt = (
        select(Observation, Site, User)
        .join(Site, Observation.site_id == Site.id, isouter=True)
        .join(User, Observation.user_id == User.id, isouter=True)
        .where(Observation.status == "in_verify")
        .where(Observation.photo_path.is_not(None))
        .order_by(Observation.created_at.desc())
        .limit(n)
    )
    rows = (await session.execute(stmt)).all()
    items: list[VerifyPendingItem] = []
    for obs, site, user in rows:
        field_count = (
            await session.execute(
                select(func.count())
                .select_from(VerifyItem)
                .where(VerifyItem.observation_id == obs.id)
                .where(VerifyItem.resolved.is_(False))
            )
        ).scalar() or 0
        submitter = (user.display_name if user and user.display_name else None) or "Guest"
        items.append(
            VerifyPendingItem(
                observation_id=obs.id,
                site_name=(site.name if site is not None else "A monitored stream"),
                photo_url=f"/api/v1/observations/{obs.id}/photo" if obs.photo_path else None,
                submitter=submitter,
                submitted_at=(obs.created_at.isoformat() if obs.created_at else ""),
                field_count=int(field_count),
            )
        )
    return VerifyPendingOut(items=items)


@router.post("/{item_id}/vote", response_model=VoteResult)
async def cast_vote(
    item_id: int,
    payload: VoteIn,
    session: AsyncSession = Depends(get_session),
) -> VoteResult:
    """Record a verification vote and recompute the observation's trust + state."""
    if payload.answer not in VALID_ANSWERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"answer must be one of {sorted(VALID_ANSWERS)}",
        )

    item = await session.get(VerifyItem, item_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="verify item not found")

    # Crew-mates are down-weighted (PRD); the trust math applies the 0.5 weight.
    voter_id = payload.voter_id or "demo-keeper"
    session.add(
        Vote(
            verify_item_id=item_id,
            voter_kind=payload.voter_kind,
            voter_id=voter_id,
            answer=payload.answer,
            ms_taken=payload.ms_taken,
            weight=0.5 if payload.voter_kind == "member" else 1.0,
            # Record the experiment arm the voter was in (same assignment the
            # /verify/next card used), for the verification-lift metric.
            arm=assign_arm(voter_id, item_id),
        )
    )
    await session.flush()

    trust, obs_status, _votes = await recompute_trust(session, item.observation_id)
    await session.commit()

    return VoteResult(
        recorded=True,
        observation_id=item.observation_id,
        observation_status=obs_status,
        trust=trust,
    )
