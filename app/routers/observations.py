"""Observations endpoints (Perfect 6 #3 and #5).

POST /observations                 — submit a field check (answers + feeling)
POST /observations/{id}/photos     — upload a processed photo (blur/pHash/EXIF)
GET  /observations/{id}/status     — receipt + live verification status

The AI only *asks* later (verify items); here we record what the human observed,
run the safety + quality gates, draft the verify items, and return the first
receipt. Raw GPS is used once for the geofence and never persisted (PRD privacy).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import receipts, scoring
from app.ai.questions import FIELD_SPECS, build_verify_items
from app.db import get_session
from app.models.observation import Observation
from app.models.site import Site
from app.models.verify import VerifyItem, Vote
from app.photos import PHASH_REUSE_DISTANCE, phash_distance, process_photo
from app.schemas import (
    ObservationCreated,
    ObservationIn,
    ObservationStatusOut,
    ReceiptOut,
)

router = APIRouter(prefix="/observations", tags=["observations"])

GEOFENCE_M = 150.0
ORPHAN_DAYS = 999
_FIELD_KEYS = [spec["key"] for spec in FIELD_SPECS]


def _days_unseen(site: Site) -> int:
    if site.last_verified_at is None:
        return ORPHAN_DAYS
    return max(0, (datetime.now(UTC) - site.last_verified_at).days)


async def _within_geofence(session: AsyncSession, site: Site, lat: float, lng: float) -> bool:
    """True if (lat, lng) is within 150 m of the site (PostGIS geography).

    Both points are built from float literals (not the stored geometry) so the
    ``geography()`` overload resolves unambiguously under asyncpg.
    """
    if site.lat is None or site.lng is None:
        return True  # no reference point to check against
    # ST_DistanceSphere takes geometry points and returns metres, sidestepping
    # the ambiguous geography() overload under asyncpg.
    p_site = func.ST_SetSRID(func.ST_MakePoint(site.lng, site.lat), 4326)
    p_user = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    stmt = select(func.ST_DistanceSphere(p_site, p_user))
    metres = (await session.execute(stmt)).scalar()
    return metres is not None and float(metres) <= GEOFENCE_M


async def _verifier_count(session: AsyncSession, observation_id: int) -> int:
    """Distinct decisive (yes/no) votes across an observation's verify items."""
    stmt = (
        select(func.count(Vote.id))
        .join(VerifyItem, Vote.verify_item_id == VerifyItem.id)
        .where(VerifyItem.observation_id == observation_id)
        .where(Vote.answer.in_(("yes", "no")))
    )
    return int((await session.execute(stmt)).scalar() or 0)


def _build_receipt(obs: Observation, site: Site, verifier_count: int) -> ReceiptOut:
    gap_before = obs.gap_days_closed if obs.gap_days_closed is not None else 0
    return ReceiptOut(
        site_name=site.name,
        waterbody=site.waterbody or "River",
        city=site.city or "",
        gap_before=gap_before,
        gap_after=0,
        rain_context=receipts.rain_context(site.rain_48h_mm or 0.0),
        verifier_count=verifier_count,
        fhir_id=obs.fhir_bundle_id,
        sentinel_line=receipts.sentinel_line(obs.answers or {}),
        state=receipts.state_label(obs.status),
        date_label=receipts.date_label(obs.created_at),
    )


@router.post("", response_model=ObservationCreated, status_code=status.HTTP_201_CREATED)
async def create_observation(
    payload: ObservationIn,
    session: AsyncSession = Depends(get_session),
) -> ObservationCreated:
    """Submit a field check: safety + quality gates, then draft verify items.

    Safety refusals return 403 + ``safety_reason`` (PRD). A pipe/outfall answer
    routes the observation straight to expert review.
    """
    site = (
        await session.execute(select(Site).where(Site.external_id == payload.site_code))
    ).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    # Geofence (raw GPS discarded immediately after the check).
    geo_ok = True
    if payload.lat is not None and payload.lng is not None:
        geo_ok = await _within_geofence(session, site, payload.lat, payload.lng)
        if not geo_ok:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "safety_reason": "outside_geofence",
                    "message": "Move within 150 m of the site to log a check.",
                },
            )

    answers = payload.answers or {}
    pipe_flag = answers.get("q-pipe") == "yes"
    answered = sum(1 for k in _FIELD_KEYS if answers.get(k))
    completeness = answered / len(_FIELD_KEYS) if _FIELD_KEYS else 0.0
    photo_ok = payload.photo_count >= 2
    quality_q = scoring.quality(completeness, photo_ok=photo_ok, geo_ok=geo_ok)

    obs = Observation(
        site_id=site.id,
        answers=answers,
        feeling=payload.feeling,
        photo_count=payload.photo_count,
        pipe_flag=pipe_flag,
        geom_ok=geo_ok,
        quality=quality_q,
        gap_days_closed=_days_unseen(site),
        status="expert" if pipe_flag else "in_verify",
    )
    session.add(obs)
    await session.flush()  # assign obs.id

    # "AI asks" — draft one neutral verify item per answered field (+ gold items).
    drafted = build_verify_items(answers)
    for item in drafted:
        session.add(VerifyItem(observation_id=obs.id, **item))

    obs.fhir_bundle_id = receipts.fhir_short_id(obs.id)
    await session.commit()
    await session.refresh(obs)

    receipt = _build_receipt(obs, site, verifier_count=0)
    return ObservationCreated(
        id=obs.id,
        status=obs.status,
        verify_item_count=len(drafted),
        receipt=receipt,
    )


@router.post("/{observation_id}/photos")
async def upload_photo(
    observation_id: int,
    file: UploadFile = File(...),
    kind: str = Form("upstream"),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Upload one observation photo.

    Runs EXIF strip + Laplacian blur score + face blur + pHash, rejects reused
    images (pHash distance < 8 against the site's past photos), and stores the
    processed bytes. A blurry photo returns 422 ``retake_photo``.
    """
    obs = await session.get(Observation, observation_id)
    if obs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="observation not found")

    raw = await file.read()
    try:
        processed = process_photo(raw, observation_id=observation_id, kind=kind)
    except Exception as exc:  # unreadable / not an image
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"reason": "unreadable_image", "message": str(exc)[:120]},
        ) from exc

    if processed.is_blurry:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"reason": "retake_photo", "message": "Photo looks blurry — retake it."},
        )

    # Reject reused images from the same site's recent observations (anti-cheat).
    if obs.site_id is not None:
        past = (
            await session.execute(
                select(Observation.photo_phash)
                .where(Observation.site_id == obs.site_id)
                .where(Observation.id != obs.id)
                .where(Observation.photo_phash.is_not(None))
            )
        ).scalars().all()
        for prior in past:
            if phash_distance(processed.phash, prior) < PHASH_REUSE_DISTANCE:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"reason": "duplicate_photo", "message": "This photo was already used."},
                )

    obs.photo_path = processed.path
    obs.photo_phash = processed.phash
    obs.photo_count = (obs.photo_count or 0) + 1
    await session.commit()
    return {
        "observation_id": observation_id,
        "kind": kind,
        "blur_score": round(processed.blur_score, 1),
        "faces_blurred": processed.faces_blurred,
        "phash": processed.phash,
    }


@router.get("/{observation_id}/status", response_model=ObservationStatusOut)
async def observation_status(
    observation_id: int,
    session: AsyncSession = Depends(get_session),
) -> ObservationStatusOut:
    """Live receipt + verification status for one observation."""
    obs = await session.get(Observation, observation_id)
    if obs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="observation not found")
    site = await session.get(Site, obs.site_id) if obs.site_id else None
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    verifier_count = await _verifier_count(session, observation_id)
    return ObservationStatusOut(
        id=obs.id,
        status=obs.status,
        trust=obs.trust,
        verifier_count=verifier_count,
        receipt=_build_receipt(obs, site, verifier_count),
    )
