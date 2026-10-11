"""Community endpoints (Track 5 — sustained participation, ethical framing).

GET /community/standings            — per-city collective progress, ranked by usefulness
GET /community/challenges[?city=]   — this-period field challenges derived live from sites

Deliberately COLLECTIVE (city / crew), never a per-person points leaderboard
(API CLAUDE.md hard rule + the RiverKin design-psychology model: social proof by
*usefulness*, not vanity). Everything here is computed live from the real OAH
sites and submitted observations — no mock data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models.community_post import CommunityPost
from app.models.observation import Observation
from app.models.site import Site
from app.models.user import User
from app.ratelimit import limiter
from app.routers.auth import current_user

router = APIRouter(prefix="/community", tags=["community"])

FRESH_NEED = 0.3  # a site is "fresh" below this need score (matches /metrics)
RAIN_MM = 20.0  # after-the-rain threshold (matches the scheduled job)


class CityStanding(BaseModel):
    city: str
    country: str | None = None
    sites_total: int
    sites_fresh: int
    coverage_pct: int
    gaps_closed: int  # cumulative days-unseen closed by verified checks
    checks_7d: int  # field checks submitted in the last 7 days
    rank: int


class Challenge(BaseModel):
    id: str
    city: str | None
    title: str
    detail: str
    target: int
    progress: int
    kind: str  # after-rain | orphan | coverage


@router.get("/standings", response_model=list[CityStanding])
async def standings(
    session: AsyncSession = Depends(get_session),
) -> list[CityStanding]:
    """Per-city collective progress, most-covered first (usefulness, not vanity)."""
    since = datetime.now(UTC) - timedelta(days=7)
    rows: list[CityStanding] = []
    cities = (
        (await session.execute(select(Site.city, Site.country).distinct()))
        .all()
    )
    for city, country in cities:
        if not city:
            continue
        total = int(
            (await session.execute(
                select(func.count(Site.id)).where(Site.city == city)
            )).scalar() or 0
        )
        fresh = int(
            (await session.execute(
                select(func.count(Site.id)).where(
                    Site.city == city, Site.need_score < FRESH_NEED
                )
            )).scalar() or 0
        )
        gaps = int(
            (await session.execute(
                select(func.coalesce(func.sum(Observation.gap_days_closed), 0))
                .join(Site, Observation.site_id == Site.id)
                .where(Site.city == city)
            )).scalar() or 0
        )
        checks = int(
            (await session.execute(
                select(func.count(Observation.id))
                .join(Site, Observation.site_id == Site.id)
                .where(Site.city == city, Observation.created_at >= since)
            )).scalar() or 0
        )
        rows.append(
            CityStanding(
                city=city,
                country=country,
                sites_total=total,
                sites_fresh=fresh,
                coverage_pct=round(100 * fresh / total) if total else 0,
                gaps_closed=gaps,
                checks_7d=checks,
                rank=0,
            )
        )
    rows.sort(key=lambda r: (r.coverage_pct, r.gaps_closed), reverse=True)
    for i, r in enumerate(rows, start=1):
        r.rank = i
    return rows


@router.get("/challenges", response_model=list[Challenge])
async def challenges(
    city: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[Challenge]:
    """This-period field challenges, derived live from sites needing a look.

    No fake urgency: every target is a real count of sites in that state right now.
    """
    base = select(Site)
    if city:
        base = base.where(Site.city == city)
    sites = (await session.execute(base)).scalars().all()
    if not sites:
        return []

    now = datetime.now(UTC)

    def days_unseen(s: Site) -> int:
        if s.last_verified_at is None:
            return 999
        return max(0, (now - s.last_verified_at).days)

    after_rain = [s for s in sites if (s.rain_48h_mm or 0) >= RAIN_MM and days_unseen(s) >= 3]
    orphans = [s for s in sites if days_unseen(s) >= 21]
    needing = [s for s in sites if (s.need_score or 0) >= FRESH_NEED]

    scope = city or "every city"
    out: list[Challenge] = []
    if after_rain:
        out.append(Challenge(
            id=f"after-rain-{city or 'all'}",
            city=city,
            title="After the rain",
            detail=f"{len(after_rain)} sites in {scope} had heavy rain and are due a check.",
            target=len(after_rain), progress=0, kind="after-rain",
        ))
    if orphans:
        out.append(Challenge(
            id=f"orphan-{city or 'all'}",
            city=city,
            title="Nobody's watching",
            detail=f"{len(orphans)} sites in {scope} haven't been seen in 3+ weeks.",
            target=len(orphans), progress=0, kind="orphan",
        ))
    if needing:
        out.append(Challenge(
            id=f"coverage-{city or 'all'}",
            city=city,
            title="Lift the coverage",
            detail=f"{len(needing)} sites in {scope} need attention to turn the map green.",
            target=len(needing), progress=0, kind="coverage",
        ))
    return out


# ---- Community feed (short, public, pseudonymous notes) --------------------

MAX_POST = 300


class CommunityPostIn(BaseModel):
    author_key: str = Field(min_length=1, max_length=64)
    author_name: str | None = Field(default=None, max_length=80)
    body: str = Field(min_length=1, max_length=MAX_POST)
    site_code: str | None = Field(default=None, max_length=64)


class CommunityPostOut(BaseModel):
    id: int
    author_name: str
    body: str
    site_name: str | None = None
    site_code: str | None = None
    created_at: str  # ISO8601


@router.get("/posts", response_model=list[CommunityPostOut])
async def list_posts(
    limit: int = Query(default=30, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> list[CommunityPostOut]:
    """The shared community feed — recent short notes, newest first."""
    rows = (
        await session.execute(
            select(CommunityPost, Site)
            .join(Site, CommunityPost.site_id == Site.id, isouter=True)
            .order_by(CommunityPost.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        CommunityPostOut(
            id=p.id,
            author_name=p.author_name or "Guest",
            body=p.body,
            site_name=site.name if site is not None else None,
            site_code=site.external_id if site is not None else None,
            created_at=(p.created_at.isoformat() if p.created_at else ""),
        )
        for p, site in rows
    ]


@router.post("/posts", response_model=CommunityPostOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("8/minute")
async def create_post(
    request: Request,
    payload: CommunityPostIn,
    session: AsyncSession = Depends(get_session),
    author: User | None = Depends(current_user),
) -> CommunityPostOut:
    """Post a short note to the community feed. Pseudonymous and rate-limited;
    text only (no images) so moderation stays light."""
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="empty post")

    site: Site | None = None
    if payload.site_code:
        site = (
            await session.execute(select(Site).where(Site.external_id == payload.site_code))
        ).scalar_one_or_none()

    # Signed-in author's display name wins; else the provided name, else Guest.
    name = (
        (author.display_name if author else None)
        or (payload.author_name or "").strip()
        or "Guest"
    )

    post = CommunityPost(
        author_key=payload.author_key[:64],
        author_name=name[:80],
        body=body[:MAX_POST],
        site_id=site.id if site else None,
        user_id=author.id if author else None,
    )
    session.add(post)
    await session.commit()
    await session.refresh(post)

    return CommunityPostOut(
        id=post.id,
        author_name=post.author_name,
        body=post.body,
        site_name=site.name if site else None,
        site_code=site.external_id if site else None,
        created_at=post.created_at.isoformat() if post.created_at else "",
    )
