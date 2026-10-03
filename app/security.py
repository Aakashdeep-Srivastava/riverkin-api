"""Password hashing (bcrypt) + JWT issue/verify for adult accounts.

HS256 signed with ``settings.JWT_SECRET`` (PRD security section). Tokens carry the
user id (``sub``), ``role`` and ``name`` so the frontend can greet the user and
gate researcher routes without a second round-trip.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(days=7)  # demo-friendly; shorten for production
OIDC_STATE_TTL = timedelta(minutes=15)  # how long a sign-in attempt stays valid


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(*, user_id: int, role: str, name: str) -> str:
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "name": name,
        "iat": int(now.timestamp()),
        "exp": int((now + ACCESS_TOKEN_TTL).timestamp()),
    }
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        return None


def create_oidc_state(nonce: str) -> str:
    """A short-lived, signed OIDC ``state`` value.

    Signing the state with our own secret lets the callback prove the request
    was started by us *without* relying on a cookie surviving the cross-site
    round-trip from Microsoft (which breaks on local http and in strict
    browsers). This is the CSRF guard for the sign-in flow.
    """
    now = datetime.now(UTC)
    claims = {
        "nonce": nonce,
        "typ": "oidc_state",
        "iat": int(now.timestamp()),
        "exp": int((now + OIDC_STATE_TTL).timestamp()),
    }
    return jwt.encode(claims, settings.JWT_SECRET, algorithm=ALGORITHM)


def verify_oidc_state(state: str) -> bool:
    """True if ``state`` is one of our unexpired, correctly-typed state tokens."""
    try:
        claims = jwt.decode(state, settings.JWT_SECRET, algorithms=[ALGORITHM])
    except JWTError:
        return False
    return claims.get("typ") == "oidc_state"
