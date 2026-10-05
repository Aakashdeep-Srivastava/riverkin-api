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

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from app.config import settings
from app.ratelimit import limiter

router = APIRouter(prefix="/maps", tags=["maps"])

# A static image is a billable Azure Maps transaction; cap per-IP calls.
_STATIC_LIMIT = "60/minute"

# Azure Maps AAD scope (same for every tenant/account).
_MAPS_SCOPE = "https://atlas.microsoft.com/.default"
# Re-mint when within this many seconds of expiry.
_REFRESH_SKEW_SECONDS = 120

# Azure Maps "Get Map Static Image" (Render v2024-04-01). Satellite imagery is
# the default so each site shows its real location from above.
_STATIC_IMAGE_URL = "https://atlas.microsoft.com/map/static"
_STATIC_API_VERSION = "2024-04-01"
_ALLOWED_TILESETS = {
    "microsoft.imagery",
    "microsoft.base.road",
    "microsoft.base.hybrid.road",
}

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


def _mint_token() -> Any | None:
    """Return a cached/fresh Azure Maps AAD token, or None if unavailable.

    Shared by ``/maps/token`` (handed to the browser MapLibre) and
    ``/maps/static`` (used server-side to authenticate the image proxy).
    """
    if not settings.AZURE_MAPS_CLIENT_ID:
        return None

    global _cached_token
    now = time.time()
    if _cached_token is not None and _cached_token.expires_on - now > _REFRESH_SKEW_SECONDS:
        return _cached_token
    try:
        token = _get_credential().get_token(_MAPS_SCOPE)
    except Exception:
        # CredentialUnavailableError, ClientAuthenticationError, probe failures.
        return None
    _cached_token = token
    return token


@router.get("/token", response_model=None)
async def get_maps_token() -> JSONResponse | dict[str, Any]:
    """Mint an AAD access token for Azure Maps.

    Returns ``{token, clientId, expiresOn}`` on success, or 503
    ``{"detail": "maps token unavailable"}`` when no credential/role is
    available. Fails fast (never hangs) so CI stays deterministic.
    """
    # Minting does blocking credential/IMDS I/O — keep it off the event loop.
    token = await run_in_threadpool(_mint_token)
    if token is None:
        return JSONResponse(
            status_code=503, content={"detail": "maps token unavailable"}
        )

    return {
        "token": token.token,
        "clientId": settings.AZURE_MAPS_CLIENT_ID,
        "expiresOn": int(token.expires_on),
    }


@router.get("/static", response_model=None)
@limiter.limit(_STATIC_LIMIT)
async def get_static_map(
    request: Request,
    lat: float = Query(..., ge=-90.0, le=90.0),
    lng: float = Query(..., ge=-180.0, le=180.0),
    zoom: int = Query(15, ge=1, le=20),
    w: int = Query(640, ge=64, le=1280),
    h: int = Query(360, ge=64, le=1280),
    tileset: str = Query("microsoft.imagery"),
) -> Response:
    """Proxy an Azure Maps static image centred on a site's coordinates.

    The browser never holds a token: it requests this endpoint and we fetch the
    PNG server-side with the managed-identity AAD token, then stream the bytes
    back. Returns 503 when maps auth is unavailable so the frontend can fall
    back to its illustrative placeholder.
    """
    if tileset not in _ALLOWED_TILESETS:
        tileset = "microsoft.imagery"

    token = await run_in_threadpool(_mint_token)
    if token is None:
        return JSONResponse(
            status_code=503, content={"detail": "maps image unavailable"}
        )

    params = {
        "api-version": _STATIC_API_VERSION,
        "tilesetId": tileset,
        "center": f"{lng},{lat}",
        "zoom": str(zoom),
        "width": str(w),
        "height": str(h),
    }
    headers = {
        "Authorization": f"Bearer {token.token}",
        "x-ms-client-id": settings.AZURE_MAPS_CLIENT_ID or "",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(_STATIC_IMAGE_URL, params=params, headers=headers)
        resp.raise_for_status()
    except httpx.HTTPError:
        return JSONResponse(
            status_code=503, content={"detail": "maps image unavailable"}
        )

    media_type = resp.headers.get("content-type", "image/png")
    return Response(
        content=resp.content,
        media_type=media_type,
        headers={
            # Site locations don't move; let the browser/CDN hold the image a day.
            "Cache-Control": "public, max-age=86400",
            # The image is embedded cross-site (page on riverkin.online, API on
            # *.azurecontainerapps.io), so it must opt out of the API's default
            # Cross-Origin-Resource-Policy: same-site or the browser blocks it.
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )
