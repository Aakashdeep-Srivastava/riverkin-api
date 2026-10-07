"""Verify-round endpoints (Perfect 6 #4).

GET  /verify/next?n=5&voter_id=   — next items to verify (incl. hidden gold)
POST /verify/{item_id}/vote       — cast a verification vote

The AI only *asks* (the question + a weak prior); humans decide by voting
(CLAUDE.md hard rule). Gold items are injected invisibly (1 in 5) and never
flagged to the verifier. Each vote recomputes observation trust + state.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.experiment import assign_arm
from app.models.observation import Observation
from app.models.site import Site
from app.models.verify import VerifyItem, Vote
from app.schemas import VerifyCard, VerifyNextOut, VoteIn, VoteResult
from app.services import recompute_trust

router = APIRouter(prefix="/verify", tags=["verify"])

VALID_ANSWERS = {"yes", "no", "cant_tell"}


@router.get("/next", response_model=VerifyNextOut)
async def next_verify_items(
    n: int = Query(default=5, ge=1, le=20),
    voter_id: str = Query(default="demo-keeper"),
    session: AsyncSession = Depends(get_session),
) -> VerifyNextOut:
    """Return the next verify cards for this voter.

    Skips items the voter already voted on and items whose observation is no
    longer open. Gold items are included but never marked as gold in the payload.
    """
    already = select(Vote.verify_item_id).where(Vote.voter_id == voter_id)
    stmt = (
        select(VerifyItem, Observation, Site)
        .join(Observation, VerifyItem.observation_id == Observation.id)
        .join(Site, Observation.site_id == Site.id, isouter=True)
        .where(VerifyItem.resolved.is_(False))
        .where(Observation.status.in_(("in_verify", "pending", "expert")))
        .where(VerifyItem.id.not_in(already))
        .order_by(VerifyItem.created_at.asc())
        .limit(n)
    )
    rows = (await session.execute(stmt)).all()
    cards: list[VerifyCard] = []
    for item, _obs, site in rows:
        # AI-assist lift experiment: the control arm is a human-only decision, so
        # withhold the AI box. Assignment is stable per (voter, item).
        arm = assign_arm(voter_id, item.id)
        cards.append(
            VerifyCard(
                item_id=item.id,
                observation_id=item.observation_id,
                site_name=(site.name if site is not None else "A monitored stream"),
                field_code=item.field_code,
                question=item.question,
                ai_box=None if arm == "control" else item.ai_box,
                arm=arm,
            )
        )
    return VerifyNextOut(cards=cards, simulated=len(cards) == 0)


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
