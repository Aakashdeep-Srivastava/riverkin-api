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
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import authenticity, receipts, scoring, vision_fields
from app.ai import vision
from app.ai.questions import FIELD_SPECS, build_verify_items
from app.db import get_session
from app.models.observation import Observation
from app.models.site import Site
from app.models.user import User
from app.models.verify import VerifyItem, Vote
from app.photos import MEDIA_DIR, PHASH_REUSE_DISTANCE, has_exif, phash_distance, process_photo
from app.routers.auth import current_user
from app.schemas import (
    ObservationCreated,
    ObservationIn,
    ObservationStatusOut,
    ReceiptOut,
    ReceiptPhotoOut,
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


def _build_photo(obs: Observation) -> ReceiptPhotoOut | None:
    pa = obs.photo_analysis
    if not pa or not obs.photo_path:
        return None
    geo = pa.get("geotag") or {}
    return ReceiptPhotoOut(
        url=f"/api/v1/observations/{obs.id}/photo",
        summary=pa.get("summary", ""),
        tags=pa.get("tags", []),
        model=pa.get("model", "heuristic"),
        used_model=bool(pa.get("used_model", False)),
        ai_generated_likelihood=float(pa.get("ai_generated_likelihood", 0.5)),
        authenticity=int(pa.get("authenticity", 50)),
        authenticity_reason=pa.get("authenticity_reason", ""),
        captured_live=bool(pa.get("captured_live", False)),
        geotag_label=geo.get("label"),
        lat=geo.get("lat"),
        lng=geo.get("lng"),
        relevance=pa.get("relevance"),
        correlation=pa.get("correlation", []),
        escalated=bool(pa.get("escalated", False)),
        photos_count=int(pa.get("photos_count", 1)),
    )


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
        points=obs.points or 0,
        photo=_build_photo(obs),
    )


@router.post("", response_model=ObservationCreated, status_code=status.HTTP_201_CREATED)
async def create_observation(
    payload: ObservationIn,
    session: AsyncSession = Depends(get_session),
    author: User | None = Depends(current_user),
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

    # River points = River Value V (usefulness-weighted reward): more for sites
    # that needed a look, scaled by quality. First check per site → full value.
    first_visit = scoring.visit_multiplier(0, is_first_in_72h=True)
    points = round(scoring.value_score(site.need_score or 0.0, quality_q, first_visit))

    obs = Observation(
        site_id=site.id,
        answers=answers,
        feeling=payload.feeling,
        photo_count=payload.photo_count,
        pipe_flag=pipe_flag,
        geom_ok=geo_ok,
        quality=quality_q,
        points=points,
        user_id=author.id if author else None,
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
    captured_live: bool = Form(False),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Upload one observation photo and analyse it.

    Runs EXIF strip + Laplacian blur score + face blur + pHash, rejects reused
    images (pHash distance < 8 against the site's past photos), then runs the
    vision model (scene summary + AI-generated estimate) and a combined
    capture-authenticity score, and geotags with the site's coarse location. A
    blurry photo returns 422 ``retake_photo``.
    """
    obs = await session.get(Observation, observation_id)
    if obs is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="observation not found")

    raw = await file.read()
    exif_present = has_exif(raw)
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

    # Novelty vs the same site's recent photos (anti-cheat). Reject near-reuse.
    novelty: int | None = None
    if obs.site_id is not None:
        past = (
            await session.execute(
                select(Observation.photo_phash)
                .where(Observation.site_id == obs.site_id)
                .where(Observation.id != obs.id)
                .where(Observation.photo_phash.is_not(None))
            )
        ).scalars().all()
        distances = [phash_distance(processed.phash, prior) for prior in past]
        if distances:
            novelty = min(distances)
            if novelty < PHASH_REUSE_DISTANCE:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"reason": "duplicate_photo", "message": "This photo was already used."},
                )

    # Vision analysis runs on the CLEAN bytes only (EXIF stripped, faces blurred).
    analysis = await vision.analyze_image(processed.jpeg_bytes)
    auth = authenticity.score(
        captured_live=captured_live,
        exif_present=exif_present,
        phash_novelty=novelty,
        model_ai_likelihood=analysis.ai_generated_likelihood,
    )

    # Coarse, privacy-safe geotag: the geofenced site location (never raw GPS).
    site = await session.get(Site, obs.site_id) if obs.site_id else None
    geotag = None
    if site is not None and site.lat is not None and site.lng is not None:
        where = ", ".join(p for p in (site.name, site.city) if p)
        geotag = {"lat": site.lat, "lng": site.lng, "label": f"Within 150 m of {where}"}

    # --- Collective image-grounded scoring (AI asks, humans decide) --------
    # Append this photo to the observation's set, then score ALL 1–5 images
    # together: a consensus per-field read, quality from mean relevance, and an
    # authenticity that the weakest photo caps. More agreeing images → a stronger
    # (but still weak) prior; the model never fills a field or downgrades a human.
    this_photo = {
        "kind": kind,
        "summary": analysis.summary,
        "tags": analysis.tags,
        "relevance": round(analysis.relevance, 3),
        "fields": analysis.fields,
        "ai_generated_likelihood": round(analysis.ai_generated_likelihood, 3),
        "authenticity": auth.confidence,
    }
    photos = list(obs.photos or [])
    photos.append(this_photo)
    obs.photos = photos

    collective_fields = vision_fields.aggregate_photo_fields(photos)
    corr = vision_fields.correlate(obs.answers or {}, collective_fields)
    items = (
        await session.execute(
            select(VerifyItem)
            .where(VerifyItem.observation_id == obs.id)
            .order_by(VerifyItem.id)
        )
    ).scalars().all()
    for item, fc in zip(items, corr.per_field, strict=False):
        if fc.agrees is None:
            item.ai_agrees = None  # collective read abstained → no AI term
            item.ai_confidence = 0.0
        else:
            item.ai_agrees = fc.agrees
            item.ai_confidence = round(fc.confidence, 3)
        # "AI asks": replace the template question with GPT's image-grounded one
        # (intuitive, varies per scene) when the model supplied it.
        model_field = vision_fields.model_field_for(fc.key)
        gpt_q = (collective_fields.get(model_field) or {}).get("question") if model_field else None
        if gpt_q:
            item.question = gpt_q

    # Collective evidence: mean relevance across photos, weakest-photo authenticity.
    mean_relevance = sum(p["relevance"] for p in photos) / len(photos)
    min_authenticity = min(int(p["authenticity"]) for p in photos)
    answered = sum(1 for k in _FIELD_KEYS if (obs.answers or {}).get(k))
    completeness = answered / len(_FIELD_KEYS) if _FIELD_KEYS else 0.0
    photo_ok = mean_relevance >= 0.5
    obs.quality = scoring.quality(completeness, photo_ok=photo_ok, geo_ok=obs.geom_ok)
    # Reward (River points) now reflects the collective evidence quality.
    first_visit = scoring.visit_multiplier(0, is_first_in_72h=True)
    need = (site.need_score or 0.0) if site else 0.0
    obs.points = round(scoring.value_score(need, obs.quality, first_visit))

    # Escalate (never downgrade): a confident collective contradiction on a
    # pollution field routes to a human expert.
    if corr.escalate and obs.status == "in_verify":
        obs.status = "expert"

    obs.photo_path = processed.path  # hero image = latest capture
    obs.photo_phash = processed.phash
    obs.photo_count = len(photos)
    obs.photo_analysis = {
        "kind": kind,
        "summary": analysis.summary,
        "tags": analysis.tags,
        "model": analysis.model,
        "used_model": analysis.used_model,
        "ai_generated_likelihood": round(analysis.ai_generated_likelihood, 3),
        "relevance": round(mean_relevance, 3),
        "photos_count": len(photos),
        "fields": collective_fields,
        "correlation": [
            {
                "field": fc.key,
                "citizen": fc.citizen,
                "photo": fc.model_value,
                "confidence": round(fc.confidence, 3),
                "agrees": fc.agrees,
            }
            for fc in corr.per_field
        ],
        "discrepancy_count": len(corr.discrepancies),
        "escalated": corr.escalate,
        "authenticity": min_authenticity,
        "authenticity_reason": auth.reason,
        "captured_live": captured_live,
        "faces_blurred": processed.faces_blurred,
        "geotag": geotag,
    }
    await session.commit()
    return {
        "observation_id": observation_id,
        "kind": kind,
        "blur_score": round(processed.blur_score, 1),
        "faces_blurred": processed.faces_blurred,
        "phash": processed.phash,
        "analysis": obs.photo_analysis,
    }


@router.get("/{observation_id}/photo")
async def observation_photo(
    observation_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve the processed (EXIF-stripped, face-blurred) photo for a check."""
    obs = await session.get(Observation, observation_id)
    if obs is None or not obs.photo_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="photo not found")
    full = MEDIA_DIR.parent / obs.photo_path
    if not Path(full).is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="photo not found")
    return FileResponse(full, media_type="image/jpeg")


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
