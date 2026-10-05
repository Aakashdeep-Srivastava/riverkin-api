"""Per-IP rate limiting (slowapi).

Protects the API from abuse and runaway cost — especially photo upload, which
runs OpenCV plus a *paid* GPT-4o-mini call, and the auth endpoints (brute force).

Keyed by the real client IP: the first hop of ``X-Forwarded-For`` (the API sits
behind the Azure Container Apps ingress, so ``request.client.host`` is the proxy).

Storage is in-memory, so limits are enforced *per replica*; with autoscale the
effective ceiling is ``limit × replicas``. That is a sound abuse/cost guard for
the hackathon; a shared store (Redis via ``storage_uri``) would make it exact.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


def client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return get_remote_address(request)


# A generous global default for normal browsing; specific endpoints tighten it.
# Disabled under APP_ENV=test so the test suite (many requests per "IP") isn't
# throttled; active in local + production.
limiter = Limiter(
    key_func=client_ip,
    default_limits=["180/minute"],
    headers_enabled=True,  # emit X-RateLimit-* + Retry-After
    enabled=settings.APP_ENV != "test",
)

# Reusable per-endpoint limits (stricter than the global default).
WRITE_LIMIT = "30/minute"  # observation create, challenge join, votes
PHOTO_LIMIT = "20/minute"  # OpenCV + paid GPT vision — the most expensive path
AUTH_LIMIT = "10/minute"  # login / register — brute-force guard
