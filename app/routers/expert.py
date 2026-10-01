"""Expert queue endpoints (Perfect 6 #6, supporting).

GET /expert/queue    — items escalated for expert review

Stub only. Escalation rules and expert actions come from the PRD.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/expert", tags=["expert"])


@router.get("/queue")
async def expert_queue() -> dict[str, Any]:
    """List observations escalated to the expert queue.

    TODO(PRD): escalation criteria, ordering, expert decision actions, and the
    exact queue item response shape.
    """
    return {"items": [], "simulated": True}
