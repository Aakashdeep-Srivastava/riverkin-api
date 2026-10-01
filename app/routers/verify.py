"""Verify-round endpoints (Perfect 6 #4).

GET  /verify/next               — next item to verify (incl. gold items)
POST /verify/{item_id}/vote     — cast a verification vote

Stubs only. Gold-item seeding, consensus, and trust scoring come from the PRD.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.ai.questions import generate_questions

router = APIRouter(prefix="/verify", tags=["verify"])


@router.get("/next")
async def next_verify_item() -> dict[str, Any]:
    """Return the next item for the current verifier.

    The AI only *asks* questions here; humans decide (CLAUDE.md hard rule).

    TODO(PRD): real item selection, gold-item injection ratio, and the exact
    item/question payload shape.
    """
    questions = generate_questions(observation_context={})
    return {
        "item_id": None,
        "questions": questions,
        "is_gold": False,
        "simulated": True,
    }


@router.post("/{item_id}/vote", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def cast_vote(item_id: int) -> dict[str, Any]:
    """Record a verification vote for an item.

    TODO(PRD): accept the vote payload, score against gold items, update
    observer/verifier trust via app.scoring.trust_score, and advance the
    verification state machine.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="cast_vote not implemented — TODO(PRD)",
    )
