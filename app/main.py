"""FastAPI application entrypoint.

- CORS from settings (CORS_ORIGINS comma list)
- GET /healthz liveness probe
- /api/v1 routers (sites, observations, verify, expert, fhir, auth, maps)
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import (
    auth,
    community,
    crews,
    expert,
    fhir,
    maps,
    metrics,
    missions,
    observations,
    sites,
    verify,
)

app = FastAPI(
    title="RiverKin API",
    version="0.1.0",
    description="RiverKin backend — IEEE OneAquaHealth Global Hackathon 2026 (Track 5).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
