"""Sites endpoints (Perfect 6 #1).

GET /sites                 — all OAH sites with live need score + attention
GET /sites/{oah_code}      — a single site
GET /sites/{oah_code}/timeline — recent checks / rain (minimal for now)

Backed by the seeded 106-site OAH table (see app/seed.py). ``need_score`` and
``attention`` come from app/scoring.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import oah, scoring
from app.db import get_session
from app.models.observation import Observation
from app.models.site import Site
from app.schemas import SiteOut, SiteTimelineOut

router = APIRouter(prefix="/sites", tags=["sites"])

ORPHAN_DAYS = 999

# Shown anywhere OAH baseline data surfaces (ODbL/OAH attribution, see README).
OAH_ATTRIBUTION = "Site, ecology & health-risk data: OneAquaHealth project (oneaquahealth.eu)"


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
    city: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[SiteOut]:
    """All sites, most-urgent first. Optional ``city`` filter."""
    stmt = select(Site)
    if city:
        stmt = stmt.where(Site.city == city)
    rows = (await session.execute(stmt)).scalars().all()
    out = [_to_out(s) for s in rows]
    out.sort(key=lambda s: s.need_score, reverse=True)
    return out


@router.get("/{oah_code}", response_model=SiteOut)
async def get_site(
    oah_code: str,
    session: AsyncSession = Depends(get_session),
) -> SiteOut:
    stmt = select(Site).where(Site.external_id == oah_code)
    site = (await session.execute(stmt)).scalar_one_or_none()
    if site is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="site not found")
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
