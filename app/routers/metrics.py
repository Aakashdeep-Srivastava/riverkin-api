"""Researcher metrics (Perfect 6 #6, supporting the R1 KPI row).

GET /metrics — coverage + quality KPIs for the researcher dashboard.

North-star (PRD): coverage freshness — the share of OAH sites that are fresh
(need < 0.3). Counts are computed live from the seeded sites and submitted
observations.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.observation import Observation
from app.models.site import Site

router = APIRouter(prefix="/metrics", tags=["metrics"])


class MetricsOut(BaseModel):
    sites_total: int
    sites_needing_attention: int
    verified_this_month: int
    open_expert_reviews: int
    coverage_fresh_pct: int
    simulated: bool = True


async def _count(session: AsyncSession, stmt) -> int:
    return int((await session.execute(stmt)).scalar() or 0)


@router.get("", response_model=MetricsOut)
async def metrics(session: AsyncSession = Depends(get_session)) -> MetricsOut:
    sites_total = await _count(session, select(func.count(Site.id)))
    # "Needs attention" = need score in the amber/urgent bands (>= 0.3).
    needing = await _count(
        session, select(func.count(Site.id)).where(Site.need_score >= 0.3)
    )
    fresh = await _count(
        session, select(func.count(Site.id)).where(Site.need_score < 0.3)
    )
    verified = await _count(
        session,
        select(func.count(Observation.id)).where(
            Observation.status.in_(("community-verified", "final"))
        ),
    )
    open_expert = await _count(
        session, select(func.count(Observation.id)).where(Observation.status == "expert")
    )
    coverage = round(100 * fresh / sites_total) if sites_total else 0
    return MetricsOut(
        sites_total=sites_total,
        sites_needing_attention=needing,
        verified_this_month=verified,
        open_expert_reviews=open_expert,
        coverage_fresh_pct=coverage,
    )
