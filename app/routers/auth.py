"""Auth endpoints.

POST /auth/token    — issue a JWT (stub)
GET  /auth/me       — current principal (stub)

Stubs only. Real identity model, roles, and token claims come from the PRD
Security/privacy section.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", status_code=status.HTTP_501_NOT_IMPLEMENTED)
async def issue_token() -> dict[str, Any]:
    """Issue a JWT for a verified principal.

    TODO(PRD): real credential exchange and signed JWT (HS256 with
    settings.JWT_SECRET), including role/trust claims.
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="issue_token not implemented — TODO(PRD)",
    )


@router.get("/me")
async def current_principal() -> dict[str, Any]:
    """Return the current authenticated principal.

    TODO(PRD): decode the bearer JWT and return the real principal + roles.
    """
    return {"authenticated": False, "simulated": True}
