"""Azure Maps token endpoint.

GET /maps/token — mint a short-lived Microsoft Entra (AAD) access token for
Azure Maps so the browser never holds a subscription key.

The API container app has a system-assigned managed identity with the
"Azure Maps Data Reader" role on the Azure Maps account. ``DefaultAzureCredential``
uses that identity in Azure and falls back to ``az login`` locally. When no
credential/role is available (e.g. CI, or local without an Azure login) the
endpoint fails fast with 503 instead of hanging.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings

router = APIRouter(prefix="/maps", tags=["maps"])

# Azure Maps AAD scope (same for every tenant/account).
_MAPS_SCOPE = "https://atlas.microsoft.com/.default"
# Re-mint when within this many seconds of expiry.
_REFRESH_SKEW_SECONDS = 120

# Module-level singletons, created lazily on first use.
_credential: Any = None
_cached_token: Any = None  # azure.core.credentials.AccessToken


def _get_credential() -> Any:
    """Return a lazily-created DefaultAzureCredential singleton.

    Constructed with ``exclude_interactive_browser_credential=True`` so a
    headless environment (CI, container) never blocks on an interactive prompt.
    """
    global _credential
    if _credential is None:
        from azure.identity import DefaultAzureCredential

        _credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=True,
        )
    return _credential


@router.get("/token", response_model=None)
async def get_maps_token() -> JSONResponse | dict[str, Any]:
    """Mint an AAD access token for Azure Maps.

    Returns ``{token, clientId, expiresOn}`` on success, or 503
    ``{"detail": "maps token unavailable"}`` when no credential/role is
    available. Fails fast (never hangs) so CI stays deterministic.
    """
    # No client id configured -> nothing to hand the browser; fail fast before
    # touching any credential/network.
    if not settings.AZURE_MAPS_CLIENT_ID:
        return JSONResponse(
            status_code=503, content={"detail": "maps token unavailable"}
        )

    global _cached_token

    now = time.time()
    if _cached_token is not None and _cached_token.expires_on - now > _REFRESH_SKEW_SECONDS:
        token = _cached_token
    else:
        try:
            credential = _get_credential()
            token = credential.get_token(_MAPS_SCOPE)
            _cached_token = token
        except Exception:
            # CredentialUnavailableError, ClientAuthenticationError, probe
            # failures, etc. Never log the exception detail or token.
            return JSONResponse(
                status_code=503, content={"detail": "maps token unavailable"}
            )

    return {
        "token": token.token,
        "clientId": settings.AZURE_MAPS_CLIENT_ID,
        "expiresOn": int(token.expires_on),
    }
