"""Observations endpoints (Perfect 6 #3 and #5).

POST /observations                 — submit an observation + photo
GET  /observations/{id}/status     — receipt + verification status

Stubs only. Photo processing (blur, pHash, EXIF strip, face blur), geofence,
and the verification state machine come from the PRD.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/observations", tags=["observations"])


@router.post("", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def create_observation() -> dict[str, Any]:
    """Submit a new observation with a photo.

    TODO(PRD): accept multipart photo + fields; run blur score, EXIF strip,
    face blur and pHash; enforce geofence (no raw GPS persisted); store
    processed photo in Azure Blob; kick off verification via BackgroundTasks.
    Safety refusals must return 403 + ``safety_reason``.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="create_observation not implemented — TODO(PRD)",
    )


@router.get("/{observation_id}/status")
async def observation_status(observation_id: int) -> dict[str, Any]:
    """Receipt + current verification status for an observation.

    TODO(PRD): real status machine, reliability score, reward value, and the
    exact receipt response shape.
    """
    return {
        "id": observation_id,
        "status": "submitted",
        "reliability_score": None,
        "simulated": True,
    }
