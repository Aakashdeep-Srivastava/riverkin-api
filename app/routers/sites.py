"""Sites endpoints (Perfect 6 #1).

GET /sites           — list sites with need score
GET /sites/{id}      — single site detail

Placeholder responses only. Exact response shapes come from the PRD API spec.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/sites", tags=["sites"])


# TODO(PRD): replace placeholder dicts with real Pydantic response models and
# DB-backed queries. Seed from data/oah_sites.json (106 OAH sites).
_PLACEHOLDER_SITES: list[dict[str, Any]] = [
    {
        "id": 1,
        "external_id": "oah-0001",
        "name": "Placeholder Site A",
        "need_score": 0.0,
        "simulated": True,
    },
]


@router.get("")
async def list_sites() -> dict[str, Any]:
    """List monitored sites with their latest need score.

    TODO(PRD): pagination, filtering by catchment/need, real need_score from
    app.scoring.need_score, and the exact response envelope.
    """
    return {"items": _PLACEHOLDER_SITES, "simulated": True}


@router.get("/{site_id}")
async def get_site(site_id: int) -> dict[str, Any]:
    """Return a single site by id.

    TODO(PRD): full site detail incl. recent observations and need breakdown.
    """
    for site in _PLACEHOLDER_SITES:
        if site["id"] == site_id:
            return site
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")
