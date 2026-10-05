"""Strava OAuth — link a runner's account and import recent activities.

Connecting Strava is per-user (not a login): a signed-in Keeper links their
Strava so their riverside runs/walks surface as "patrols". The browser never
sees the Strava tokens — they're stored server-side and refreshed as needed.

Config-gated: with STRAVA_CLIENT_ID/SECRET unset the button is hidden and every
endpoint fails fast, exactly like the Microsoft sign-in flow. Strava is not
OIDC, so the callback reads the athlete profile straight from the token JSON.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models.strava_account import StravaAccount
from app.models.user import User
from app.routers.auth import current_user
from app.security import decode_token

router = APIRouter(prefix="/strava", tags=["strava"])

AUTHORIZE = "https://www.strava.com/oauth/authorize"
TOKEN = "https://www.strava.com/oauth/token"
ACTIVITIES = "https://www.strava.com/api/v3/athlete/activities"
SCOPE = "read,activity:read"
_ALG = "HS256"
_STATE_TTL = 900  # seconds a connect attempt stays valid


def _configured() -> bool:
    return bool(settings.STRAVA_CLIENT_ID and settings.STRAVA_CLIENT_SECRET)


def _sign_state(user_id: int) -> str:
    """Signed, short-lived state carrying the linking user's id (CSRF guard)."""
    now = int(time.time())
    return jwt.encode(
        {"uid": user_id, "typ": "strava_state", "iat": now, "exp": now + _STATE_TTL},
        settings.JWT_SECRET,
        algorithm=_ALG,
    )


def _read_state(state: str) -> int | None:
    try:
        claims = jwt.decode(state, settings.JWT_SECRET, algorithms=[_ALG])
    except JWTError:
        return None
    if claims.get("typ") != "strava_state":
        return None
    try:
        return int(claims["uid"])
    except (KeyError, TypeError, ValueError):
        return None


def _fail_redirect(reason: str) -> RedirectResponse:
    web = settings.WEB_URL.rstrip("/")
    return RedirectResponse(
        f"{web}/me?strava=error&reason={reason}", status_code=status.HTTP_302_FOUND
    )


@router.get("/config")
async def strava_config() -> dict[str, bool]:
    """Whether Strava linking is available (drives the UI button)."""
    return {"enabled": _configured()}


@router.get("/status")
async def strava_status(
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Whether the signed-in user has linked Strava."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="sign in required"
        )
    acct = (
        await session.execute(
            select(StravaAccount).where(StravaAccount.user_id == user.id)
        )
    ).scalar_one_or_none()
    return {
        "enabled": _configured(),
        "connected": acct is not None,
        "athlete_name": acct.athlete_name if acct else None,
    }


@router.get("/connect")
async def strava_connect(token: str) -> RedirectResponse:
    """Begin the Strava OAuth redirect for the signed-in user.

    The user's identity rides in the signed ``state`` because a browser
    navigation can't carry the Authorization header; ``token`` is the app JWT
    the frontend already holds.
    """
    if not _configured():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Strava is not configured"
        )
    claims = decode_token(token)
    if not claims or "sub" not in claims:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        )
    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token"
        ) from None
    params = {
        "client_id": settings.STRAVA_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.STRAVA_REDIRECT_URI,
        "approval_prompt": "auto",
        "scope": SCOPE,
        "state": _sign_state(user_id),
    }
    return RedirectResponse(
        AUTHORIZE + "?" + urlencode(params), status_code=status.HTTP_302_FOUND
    )


@router.get("/callback")
async def strava_callback(
    request: Request, session: AsyncSession = Depends(get_session)
) -> RedirectResponse:
    """Exchange the code, store tokens, and send the browser back to /me."""
    if request.query_params.get("error"):
        return _fail_redirect("denied")
    code = request.query_params.get("code")
    user_id = _read_state(request.query_params.get("state") or "")
    if not code or user_id is None:
        return _fail_redirect("bad_state")
    user = await session.get(User, user_id)
    if user is None:
        return _fail_redirect("bad_state")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                TOKEN,
                data={
                    "client_id": settings.STRAVA_CLIENT_ID,
                    "client_secret": settings.STRAVA_CLIENT_SECRET,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
        resp.raise_for_status()
        tok = resp.json()
    except (httpx.HTTPError, ValueError):
        return _fail_redirect("exchange")

    athlete = tok.get("athlete") or {}
    athlete_id = athlete.get("id")
    if not athlete_id or "access_token" not in tok or "refresh_token" not in tok:
        return _fail_redirect("exchange")
    name = (
        " ".join(x for x in [athlete.get("firstname"), athlete.get("lastname")] if x)
        or None
    )

    acct = (
        await session.execute(
            select(StravaAccount).where(StravaAccount.user_id == user_id)
        )
    ).scalar_one_or_none()
    if acct is None:
        acct = StravaAccount(user_id=user_id, athlete_id=athlete_id)
        session.add(acct)
    acct.athlete_id = athlete_id
    acct.athlete_name = name
    acct.access_token = tok["access_token"]
    acct.refresh_token = tok["refresh_token"]
    acct.expires_at = int(tok.get("expires_at", 0))
    await session.commit()

    return RedirectResponse(
        f"{settings.WEB_URL.rstrip('/')}/me?strava=connected",
        status_code=status.HTTP_302_FOUND,
    )


async def _valid_access_token(acct: StravaAccount, session: AsyncSession) -> str | None:
    """Return a non-expired access token, refreshing via Strava if needed."""
    if acct.expires_at - int(time.time()) > 60:
        return acct.access_token
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                TOKEN,
                data={
                    "client_id": settings.STRAVA_CLIENT_ID,
                    "client_secret": settings.STRAVA_CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": acct.refresh_token,
                },
            )
        resp.raise_for_status()
        tok = resp.json()
    except (httpx.HTTPError, ValueError):
        return None
    acct.access_token = tok["access_token"]
    acct.refresh_token = tok.get("refresh_token", acct.refresh_token)
    acct.expires_at = int(tok.get("expires_at", 0))
    await session.commit()
    return acct.access_token


@router.get("/activities")
async def strava_activities(
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Recent runs/walks for the linked athlete, shaped as 'patrols'."""
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="sign in required"
        )
    acct = (
        await session.execute(
            select(StravaAccount).where(StravaAccount.user_id == user.id)
        )
    ).scalar_one_or_none()
    if acct is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="strava not linked"
        )
    access = await _valid_access_token(acct, session)
    if access is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="strava unavailable"
        )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                ACTIVITIES,
                params={"per_page": 10, "page": 1},
                headers={"Authorization": f"Bearer {access}"},
            )
        resp.raise_for_status()
        raw = resp.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="strava unavailable"
        ) from None

    patrols = [
        {
            "id": a.get("id"),
            "name": a.get("name"),
            "type": a.get("sport_type") or a.get("type"),
            "distance_m": a.get("distance"),
            "moving_time_s": a.get("moving_time"),
            "start_date": a.get("start_date_local") or a.get("start_date"),
            "polyline": (a.get("map") or {}).get("summary_polyline"),
        }
        for a in raw
        if isinstance(a, dict)
    ]
    return {"athlete_name": acct.athlete_name, "patrols": patrols}


@router.post("/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def strava_disconnect(
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="sign in required"
        )
    acct = (
        await session.execute(
            select(StravaAccount).where(StravaAccount.user_id == user.id)
        )
    ).scalar_one_or_none()
    if acct is not None:
        await session.delete(acct)
        await session.commit()
