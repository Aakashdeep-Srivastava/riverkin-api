"""FHIR export endpoints (Perfect 6 #6).

GET /fhir/observations/{id}    — FHIR Bundle (Observation + Provenance)

Stub only. Exporting the Bundle to HAPI and the OAH IG shaping come from the PRD.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.fhir.bundle import build_observation_bundle

router = APIRouter(prefix="/fhir", tags=["fhir"])


@router.get("/observations/{observation_id}")
async def get_fhir_observation(observation_id: int) -> dict[str, Any]:
    """Return the FHIR Bundle for a verified observation.

    TODO(PRD): load the real observation, shape to the OAH IG, and POST to the
    HAPI server at settings.FHIR_BASE_URL. For now return a minimal placeholder
    Bundle built from no real data.
    """
    bundle = build_observation_bundle(observation_id=observation_id)
    return bundle.model_dump(mode="json")
