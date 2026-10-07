"""Sites endpoints (Perfect 6 #1).

GET /sites                 — all OAH sites with live need score + attention
GET /sites/{oah_code}      — a single site
GET /sites/{oah_code}/timeline — recent checks / rain (minimal for now)

Backed by the seeded 106-site OAH table (see app/seed.py). ``need_score`` and
``attention`` come from app/scoring.py.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import oah, scoring
from app.config import settings
from app.db import get_session
from app.models.observation import Observation
from app.models.site import Site
from app.schemas import SiteOut, SiteTimelineOut

router = APIRouter(prefix="/sites", tags=["sites"])

ORPHAN_DAYS = 999

# Shown anywhere OAH baseline data surfaces (ODbL/OAH attribution, see README).
OAH_ATTRIBUTION = "Site, ecology & health-risk data: OneAquaHealth project (oneaquahealth.eu)"

# In-process GET /sites cache: {city_key: (expires_monotonic, body_bytes, etag)}.
# We cache the *already-serialised* JSON, so a cache hit skips the table scan,
# the per-row scoring AND the response serialisation — it just writes bytes.
# The list is viewer-independent and only changes every few hours, so a short
# TTL is safe. Per-replica (not shared); a concurrent miss may rebuild twice,
# which is idempotent and cheap, so no lock.
_SITES_ADAPTER = TypeAdapter(list[SiteOut])
_SITES_CACHE: dict[str, tuple[float, bytes, str]] = {}


def _sites_cache_on() -> bool:
    # Disabled under tests so the module-level cache never leaks state between
    # the suite's repeated re-seeds; ETag/304 still work (rebuilt each call).
    return settings.SITES_CACHE_TTL > 0 and settings.APP_ENV != "test"


def _sites_cache_control() -> str:
    ttl = max(1, settings.SITES_CACHE_TTL)
    return f"public, max-age={ttl}, stale-while-revalidate=300"


def _sites_etag(city_key: str, rows: list[Site]) -> str:
    """Weak ETag over a cheap signature: city, row count, newest updated_at and
    the date (days_unseen changes at day granularity). Changes exactly when the
    list's content would, without serialising it."""
    newest = 0
    for s in rows:
        if s.updated_at is not None:
            newest = max(newest, int(s.updated_at.timestamp()))
    day = datetime.now(UTC).strftime("%Y%m%d")
    return f'W/"sites-{city_key}-{len(rows)}-{newest}-{day}"'


def _days_unseen(site: Site) -> int:
    if site.last_verified_at is None:
        return ORPHAN_DAYS
    delta = datetime.now(UTC) - site.last_verified_at
    return max(0, delta.days)


def _to_out(site: Site) -> SiteOut:
    days = _days_unseen(site)
    need = site.need_score if site.need_score is not None else 0.0
    return SiteOut(
        id=site.external_id or str(site.id),
        name=site.name,
        waterbody=site.waterbody,
        city=site.city,
        country=site.country,
        lat=site.lat,
        lng=site.lng,
        altitude_m=site.altitude_m,
        days_unseen=days,
        rain_48h_mm=site.rain_48h_mm or 0.0,
        need_score=round(need, 4),
        attention=scoring.attention_level(
            need, days_since_check=float(days), expert_flag_open=site.expert_flag_open
        ),
        color=scoring.need_color(
            need, expert_flag_open=site.expert_flag_open, days_since_check=float(days)
        ),
        ecology=oah.ecology_status(site.ecology),
        health_risk=oah.health_risk_band(site.health_risk),
        biodiversity=site.biodiversity,
        discharge=site.discharge,
        recency_simulated=site.simulated,
        data_attribution=OAH_ATTRIBUTION,
        simulated=site.simulated,
    )


@router.get("", response_model=list[SiteOut])
async def list_sites(
    request: Request,
    response: Response,
    city: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    """All sites, most-urgent first. Optional ``city`` filter.

    Served from a short-TTL in-process cache (see ``_SITES_CACHE``) and tagged
    with ``ETag`` + ``Cache-Control`` so repeat loads hit the browser/CDN or a
    cheap ``304`` instead of re-scanning + re-scoring every site.
    """
    key = city or "*"
    now = time.monotonic()
    cached = _SITES_CACHE.get(key)
    if cached and cached[0] > now and _sites_cache_on():
        body, etag = cached[1], cached[2]
    else:
        stmt = select(Site)
        if city:
            stmt = stmt.where(Site.city == city)
        rows = list((await session.execute(stmt)).scalars().all())
        out = [_to_out(s) for s in rows]
        out.sort(key=lambda s: s.need_score, reverse=True)
        body = _SITES_ADAPTER.dump_json(out)
        etag = _sites_etag(key, rows)
        if _sites_cache_on():
            _SITES_CACHE[key] = (now + settings.SITES_CACHE_TTL, body, etag)

    headers = {"ETag": etag, "Cache-Control": _sites_cache_control()}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    # Return pre-serialised bytes directly (response_model stays declared for the
    # OpenAPI contract; returning a Response just skips re-serialisation).
    return Response(content=body, media_type="application/json", headers=headers)


@router.get("/{oah_code}", response_model=SiteOut)
async def get_site(
    oah_code: str,
    response: Response,
    session: AsyncSession = Depends(get_session),
) -> SiteOut:
    stmt = select(Site).where(Site.external_id == oah_code)
    site = (await session.execute(stmt)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")
    # A single site is cheap, but still viewer-independent and slow-changing —
    # let the browser/CDN hold it briefly.
    response.headers["Cache-Control"] = _sites_cache_control()
    return _to_out(site)


@router.get("/{oah_code}/timeline", response_model=SiteTimelineOut)
async def site_timeline(
    oah_code: str,
    session: AsyncSession = Depends(get_session),
) -> SiteTimelineOut:
    """Checks, rain context and verifications for a site, newest first (C7).

    Combines real submitted observations with the site's rain/last-check context.
    """
    stmt = select(Site).where(Site.external_id == oah_code)
    site = (await session.execute(stmt)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")

    entries: list[dict] = []

    # Real submitted observations for this site.
    obs_rows = (
        await session.execute(
            select(Observation)
            .where(Observation.site_id == site.id)
            .order_by(Observation.created_at.desc())
            .limit(20)
        )
    ).scalars().all()
    for obs in obs_rows:
        verified = obs.status in ("community-verified", "final")
        label = (
            "Community-verified check"
            if verified
            else "Expert review" if obs.status in ("expert", "queried") else "Field check submitted"
        )
        entries.append(
            {
                "kind": "verification" if verified else "check",
                "label": label,
                "at": obs.created_at.isoformat(),
            }
        )

    # Real OAH biological/chemical baseline sample (the project's own data).
    eco = oah.ecology_status(site.ecology)
    if eco and eco.get("date"):
        status_txt = eco["status"] or "sampled"
        element = eco.get("worst_element") or "biology"
        entries.append(
            {
                "kind": "baseline",
                "label": f"OAH ecological status: {status_txt} ({element})",
                "at": eco["date"],
            }
        )

    # Real OAH One Health risk assessment.
    hr = oah.health_risk_band(site.health_risk)
    if hr and hr.get("date"):
        entries.append(
            {
                "kind": "baseline",
                "label": f"OAH One Health risk: {hr['band']} ({hr['score']})",
                "at": hr["date"],
            }
        )

    # Rain context (from the 3-hourly Open-Meteo pull).
    if site.rain_48h_mm and site.rain_48h_mm >= 20:
        entries.append(
            {
                "kind": "rain",
                "label": f"{round(site.rain_48h_mm)} mm rain in 48 h",
                "at": datetime.now(UTC).isoformat(),
            }
        )

    # Fall back to the seeded last-verified check so the timeline is never empty.
    if not obs_rows and site.last_verified_at is not None:
        entries.append(
            {
                "kind": "check",
                "label": "Last verified check",
                "at": site.last_verified_at.isoformat(),
            }
        )

    entries.sort(key=lambda e: e["at"], reverse=True)
    return SiteTimelineOut(site_id=oah_code, entries=entries, simulated=site.simulated)
