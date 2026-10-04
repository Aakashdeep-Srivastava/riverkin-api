"""Auth endpoints — adult accounts (Crew Lead, Keeper, Researcher).

POST /auth/register   — create an account, return a JWT
POST /auth/login      — exchange email + password for a JWT
GET  /auth/me         — the current principal from the bearer token

Passwords are bcrypt-hashed; tokens are HS256 JWTs (see app/security.py). Kids
never get accounts here — they are pseudonymous crew members (PRD role model).
"""

from __future__ import annotations

import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from jose import jwt as jose_jwt
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_session
from app.models.observation import Observation
from app.models.user import User
from app.schemas import AuthToken, LoginIn, RegisterIn, UserOut
from app.security import (
    create_access_token,
    create_oidc_state,
    decode_token,
    hash_password,
    verify_oidc_state,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# River Score → identity tier thresholds (cumulative River points). Identity,
# not XP: a role you grow into. Anti-farming is baked into the points (the
# visit multiplier M decays/caps), so the score can't be spammed up.
RIVER_TIERS = [
    ("Observer", 0),
    ("Explorer", 50),
    ("River Keeper", 200),
]

VALID_ROLES = {"keeper", "crew_lead", "researcher"}

# Microsoft (Entra) OIDC endpoints.
MS_AUTHORIZE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
MS_TOKEN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
MS_SCOPE = "openid email profile"
OIDC_HASH = "oidc:microsoft"  # placeholder hash — OIDC users never password-login


def _to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        role=user.role,
        display_name=user.display_name,
        large_text=user.large_text,
    )


def _token_for(user: User) -> AuthToken:
    token = create_access_token(user_id=user.id, role=user.role, name=user.display_name)
    return AuthToken(access_token=token, user=_to_out(user))


@router.post("/register", response_model=AuthToken, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterIn, session: AsyncSession = Depends(get_session)) -> AuthToken:
    if payload.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"role must be one of {sorted(VALID_ROLES)}",
        )
    email = payload.email.lower()
    exists = (
        await session.execute(select(func.count(User.id)).where(User.email == email))
    ).scalar()
    if exists:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="an account with this email already exists"
        )
    user = User(
        email=email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        display_name=payload.display_name,
        large_text=payload.large_text,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return _token_for(user)


@router.post("/login", response_model=AuthToken)
async def login(payload: LoginIn, session: AsyncSession = Depends(get_session)) -> AuthToken:
    user = (
        await session.execute(select(User).where(User.email == payload.email.lower()))
    ).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
        )
    return _token_for(user)


async def current_user(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
) -> User | None:
    """Optional principal from a bearer token (None if absent/invalid)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    claims = decode_token(authorization.split(" ", 1)[1])
    if not claims or "sub" not in claims:
        return None
    try:
        user_id = int(claims["sub"])
    except (TypeError, ValueError):
        return None
    return await session.get(User, user_id)


@router.get("/me")
async def me(user: User | None = Depends(current_user)) -> dict:
    if user is None:
        return {"authenticated": False}
    return {"authenticated": True, "user": _to_out(user).model_dump()}


@router.get("/score")
async def river_score(
    user: User | None = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """The signed-in user's permanent River Score — Σ River points over their
    checks (+ a small verified bonus), with their identity tier and progress.

    Guests get 401 here and fall back to a device-local tally in the UI.
    """
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="sign in required")

    base = int(
        (await session.execute(
            select(func.coalesce(func.sum(Observation.points), 0)).where(
                Observation.user_id == user.id
            )
        )).scalar() or 0
    )
    checks = int(
        (await session.execute(
            select(func.count(Observation.id)).where(Observation.user_id == user.id)
        )).scalar() or 0
    )
    verified = int(
        (await session.execute(
            select(func.count(Observation.id)).where(
                Observation.user_id == user.id,
                Observation.status.in_(("community-verified", "final")),
            )
        )).scalar() or 0
    )
    # Verified checks are worth more: a 25%-per-verified bonus on the base.
    score = base + round(0.25 * base * (verified / checks)) if checks else 0

    tier_name, _ = RIVER_TIERS[0]
    next_name: str | None = None
    to_next = 0
    for i, (name, at) in enumerate(RIVER_TIERS):
        if score >= at:
            tier_name = name
            if i + 1 < len(RIVER_TIERS):
                next_name, next_at = RIVER_TIERS[i + 1]
                to_next = max(0, next_at - score)
            else:
                next_name, to_next = None, 0
    return {
        "score": score,
        "checks": checks,
        "verified": verified,
        "tier": tier_name,
        "next_tier": next_name,
        "to_next": to_next,
    }


@router.get("/config")
async def auth_config() -> dict:
    """What the sign-in UI should offer (Microsoft button only if configured)."""
    return {"microsoft": bool(settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET)}


# ------------------------------------------------------------------
# Microsoft (Entra) OIDC — authorization-code flow (backend confidential client)
# ------------------------------------------------------------------
@router.get("/microsoft/login")
async def microsoft_login() -> RedirectResponse:
    """Kick off Microsoft sign-in with a signed, stateless ``state`` (CSRF).

    The state is a short-lived token signed with our own secret, so the callback
    can validate it without a cookie — robust across local http and strict
    browsers that drop the cross-site redirect cookie.
    """
    if not (settings.MS_CLIENT_ID and settings.MS_CLIENT_SECRET):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Microsoft sign-in is not configured",
        )
    state = create_oidc_state(secrets.token_urlsafe(16))
    params = {
        "client_id": settings.MS_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.MS_REDIRECT_URI,
        "response_mode": "query",
        "scope": MS_SCOPE,
        "state": state,
    }
    url = MS_AUTHORIZE.format(tenant=settings.MS_TENANT) + "?" + urlencode(params)
    return RedirectResponse(url, status_code=status.HTTP_302_FOUND)


def _fail_redirect(reason: str) -> RedirectResponse:
    return RedirectResponse(
        f"{settings.WEB_URL.rstrip('/')}/auth/complete?error={reason}",
        status_code=status.HTTP_302_FOUND,
    )


@router.get("/microsoft/callback")
async def microsoft_callback(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> RedirectResponse:
    """Handle Microsoft's redirect: exchange the code, upsert the user, issue our JWT."""
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if request.query_params.get("error"):
        return _fail_redirect(request.query_params.get("error", "denied"))
    if not code or not state or not verify_oidc_state(state):
        return _fail_redirect("bad_state")

    data = {
        "client_id": settings.MS_CLIENT_ID,
        "client_secret": settings.MS_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.MS_REDIRECT_URI,
        "scope": MS_SCOPE,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            tok = await client.post(MS_TOKEN.format(tenant=settings.MS_TENANT), data=data)
        if tok.status_code != 200:
            return _fail_redirect("token_exchange")
        id_token = tok.json().get("id_token")
        # The id_token came straight from Microsoft over TLS; read its claims.
        claims = jose_jwt.get_unverified_claims(id_token) if id_token else {}
    except Exception:
        return _fail_redirect("token_exchange")

    email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    name = claims.get("name") or (email.split("@")[0] if email else "River Keeper")
    if not email:
        return _fail_redirect("no_email")

    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            password_hash=OIDC_HASH,
            role="keeper",
            display_name=name,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

    app_token = create_access_token(user_id=user.id, role=user.role, name=user.display_name)
    return RedirectResponse(
        f"{settings.WEB_URL.rstrip('/')}/auth/complete?token={app_token}",
        status_code=status.HTTP_302_FOUND,
    )
