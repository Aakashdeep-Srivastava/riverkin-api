"""Expert queue + review endpoints (Perfect 6 #6).

GET  /expert/queue              — observations escalated for expert sign-off
POST /expert/{obs_id}/review    — confirm / amend / reject, advancing FHIR status

Escalation (PRD): a pipe/sewage flag or a split field routes an observation to
``expert``. An expert decision moves the FHIR status: preliminary → final
(confirm) or amended (amend); reject sends it back to ``queried``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.observation import Observation
from app.models.site import Site
from app.models.verify import VerifyItem, Vote

router = APIRouter(prefix="/expert", tags=["expert"])


class ExpertQueueItem(BaseModel):
    observation_id: int
    site_name: str
    status: str
    reason: str
    pipe_flag: bool
    trust: float | None
    verifier_count: int
    answers: dict[str, str]


class ExpertQueueOut(BaseModel):
    items: list[ExpertQueueItem]
    simulated: bool = True


class ReviewIn(BaseModel):
    field_code: str | None = None
    decision: str  # confirm | amend | reject
    new_value: str | None = None


class ReviewResult(BaseModel):
    observation_id: int
    status: str
    decision: str


VALID_DECISIONS = {"confirm", "amend", "reject"}


async def _verifier_count(session: AsyncSession, observation_id: int) -> int:
    stmt = (
        select(func.count(Vote.id))
        .join(VerifyItem, Vote.verify_item_id == VerifyItem.id)
        .where(VerifyItem.observation_id == observation_id)
        .where(Vote.answer.in_(("yes", "no")))
    )
    return int((await session.execute(stmt)).scalar() or 0)


@router.get("/queue", response_model=ExpertQueueOut)
async def expert_queue(session: AsyncSession = Depends(get_session)) -> ExpertQueueOut:
    """Observations awaiting expert sign-off (pipe/sewage flag or split votes)."""
    stmt = (
        select(Observation, Site)
        .join(Site, Observation.site_id == Site.id, isouter=True)
        .where(Observation.status == "expert")
        .order_by(Observation.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    items = [
        ExpertQueueItem(
            observation_id=obs.id,
            site_name=site.name if site else "A monitored stream",
            status=obs.status,
            reason="Pipe / outfall reported" if obs.pipe_flag else "Split verifier votes",
            pipe_flag=obs.pipe_flag,
            trust=obs.trust,
            verifier_count=await _verifier_count(session, obs.id),
            answers=obs.answers or {},
        )
        for obs, site in rows
    ]
    return ExpertQueueOut(items=items, simulated=len(items) == 0)


@router.post("/{obs_id}/review", response_model=ReviewResult)
async def review_observation(
    obs_id: int,
    payload: ReviewIn,
    session: AsyncSession = Depends(get_session),
) -> ReviewResult:
    """Record an expert decision and advance the FHIR status lifecycle."""
    if payload.decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"decision must be one of {sorted(VALID_DECISIONS)}",
        )
    obs = await session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="observation not found")

    if payload.decision == "confirm":
        obs.status = "final"
    elif payload.decision == "amend":
        obs.status = "amended"
        if payload.field_code and payload.new_value is not None:
            answers = dict(obs.answers or {})
            answers[payload.field_code] = payload.new_value
            obs.answers = answers
    else:  # reject
        obs.status = "queried"

    await session.commit()
    return ReviewResult(observation_id=obs.id, status=obs.status, decision=payload.decision)
