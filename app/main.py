"""FastAPI application entrypoint.

- CORS from settings (CORS_ORIGINS comma list)
- GET /healthz liveness probe
- /api/v1 routers (sites, observations, verify, expert, fhir, auth, maps)
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings
from app.ratelimit import limiter
from app.routers import (
    auth,
    challenges,
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
    strava,
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
    # Keep the API out of search indexes — it's a data backend, not content.
    "X-Robots-Tag": "noindex, nofollow",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach hardened security headers to every response."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for key, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response


# Hide the interactive docs and the live OpenAPI schema in production so the API
# surface isn't publicly browsable (the frontend still calls /api/v1/* directly;
# openapi.json for `gen:api` is exported from the app object by
# scripts/export_openapi.py, not this HTTP route). Docs stay on in local/test.
_DOCS_ENABLED = settings.APP_ENV != "production"

app = FastAPI(
    title="RiverKin API",
    version="0.1.0",
    description="RiverKin backend — IEEE OneAquaHealth Global Hackathon 2026 (Track 5).",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)

# Rate limiting (slowapi): global default + per-endpoint tightening.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/healthz", tags=["health"])
@limiter.exempt
async def healthz() -> dict[str, str]:
    """Liveness probe used by the Docker entrypoint and CI smoke test."""
    return {"status": "ok"}


@app.get("/robots.txt", include_in_schema=False)
@limiter.exempt
async def robots_txt() -> PlainTextResponse:
    """Disallow all crawlers — the API is a data backend, not indexable content."""
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


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
app.include_router(challenges.router, prefix=API_PREFIX)
app.include_router(notifications.router, prefix=API_PREFIX)
app.include_router(push.router, prefix=API_PREFIX)
app.include_router(events.router, prefix=API_PREFIX)
app.include_router(strava.router, prefix=API_PREFIX)
