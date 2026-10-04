"""FastAPI application entrypoint.

- CORS from settings (CORS_ORIGINS comma list)
- GET /healthz liveness probe
- /api/v1 routers (sites, observations, verify, expert, fhir, auth, maps)
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.routers import (
    auth,
    community,
    crews,
    events,
    expert,
    fhir,
    maps,
    metrics,
    missions,
    notifications,
    observations,
    push,
    sites,
    verify,
)

# Security response headers (the API serves JSON only, so a locked-down CSP that
# forbids any embedding/active content is safe and strong — defence in depth on
# top of HTTPS-only Azure Container Apps ingress). EU/OWASP best practice.
_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains; preload",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cross-Origin-Resource-Policy": "same-site",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach hardened security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


app = FastAPI(
    title="RiverKin API",
    version="0.1.0",
    description="RiverKin backend — IEEE OneAquaHealth Global Hackathon 2026 (Track 5).",
)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Liveness probe used by the Docker entrypoint and CI smoke test."""
    return {"status": "ok"}


# Perfect 6 routers plus maps token, all under /api/v1.
API_PREFIX = "/api/v1"
app.include_router(sites.router, prefix=API_PREFIX)
app.include_router(observations.router, prefix=API_PREFIX)
app.include_router(verify.router, prefix=API_PREFIX)
app.include_router(expert.router, prefix=API_PREFIX)
app.include_router(fhir.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
app.include_router(maps.router, prefix=API_PREFIX)
app.include_router(metrics.router, prefix=API_PREFIX)
app.include_router(crews.router, prefix=API_PREFIX)
app.include_router(missions.router, prefix=API_PREFIX)
app.include_router(community.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(push.router, prefix=API_PREFIX)
app.include_router(events.router, prefix=API_PREFIX)
