"""FHIR export endpoints (Perfect 6 #6).

GET /fhir/observations/{id}          — FHIR transaction Bundle for one check
GET /fhir/observations/{id}?post=1   — also POST it to the HAPI server (best effort)

Builds the Bundle from the real stored observation (see app/fhir/bundle.py).
Posting to HAPI is optional (the OAH sandbox has been down); it is attempted
only when ``post=1`` and never fails the read.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.fhir.bundle import build_observation_bundle
from app.models.observation import Observation
from app.models.site import Site
from app.models.verify import VerifyItem, Vote

router = APIRouter(prefix="/fhir", tags=["fhir"])


async def _verifier_count(session: AsyncSession, observation_id: int) -> int:
    stmt = (
        select(func.count(Vote.id))
        .join(VerifyItem, Vote.verify_item_id == VerifyItem.id)
        .where(VerifyItem.observation_id == observation_id)
        .where(Vote.answer.in_(("yes", "no")))
    )
    return int((await session.execute(stmt)).scalar() or 0)


@router.get("/observations/{observation_id}")
async def get_fhir_observation(
    observation_id: int,
    post: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return the FHIR Bundle for one observation (optionally POST to HAPI)."""
    obs = await session.get(Observation, observation_id)
    if obs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="observation not found")
    site = await session.get(Site, obs.site_id) if obs.site_id else None

    bundle = build_observation_bundle(
        observation_id=obs.id,
        site_external_id=site.external_id if site else None,
        site_name=site.name if site else "Unknown site",
        lat=site.lat if site else None,
        lng=site.lng if site else None,
        answers=obs.answers or {},
        feeling=obs.feeling,
        status=obs.status,
        verifier_count=await _verifier_count(session, observation_id),
        created_at=obs.created_at,
    )
    payload = bundle.model_dump(mode="json")

    posted_ok: bool | None = None
    if post and settings.FHIR_BASE_URL:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    settings.FHIR_BASE_URL.rstrip("/"),
                    json=payload,
                    headers={"Content-Type": "application/fhir+json"},
                )
                posted_ok = resp.status_code < 300
        except Exception:
            posted_ok = False

    return {
        "bundle": payload,
        "posted_to_hapi": posted_ok,
        "simulated": site.simulated if site else True,
    }
