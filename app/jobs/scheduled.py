"""Scheduled job: Open-Meteo rain pull + per-site need recompute.

Run locally with::

    python -m app.jobs.scheduled

In production an Azure Container Apps cron Job invokes this every 3 h. Rain is
regional, so we fetch one 48 h precipitation total per city (≈5 calls) and apply
it to every site in that city, then recompute N_s (app/scoring.py) and persist.
Idempotent — the API runs at 1 replica so this never races a second run.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select

from app import scoring
from app.db import SessionLocal
from app.models.site import Site

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.jobs.scheduled")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


async def _rain_48h(client: httpx.AsyncClient, lat: float, lng: float) -> float:
    """Total precipitation (mm) over the last 48 h at a point, via Open-Meteo."""
    try:
        resp = await client.get(
            OPEN_METEO_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "hourly": "precipitation",
                "past_days": 2,
                "forecast_days": 1,
                "timezone": "UTC",
            },
            timeout=20.0,
        )
        resp.raise_for_status()
        hourly = resp.json().get("hourly", {}).get("precipitation", []) or []
        return round(sum(float(x or 0.0) for x in hourly[-48:]), 1)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Open-Meteo fetch failed for (%s,%s): %s", lat, lng, exc)
        return 0.0


def _visit_share(days_unseen: float) -> float:
    """Rough share of ideal visits over 90 days from recency (no visit log yet)."""
    return max(0.0, 1.0 - days_unseen / 42.0)


async def run() -> int:
    """Pull rain per city and recompute need for every site. Returns site count."""
    from datetime import UTC, datetime

    async with SessionLocal() as session:
        sites = (await session.execute(select(Site))).scalars().all()
        if not sites:
            logger.info("no sites to score — run app.seed first")
            return 0

        # One representative coordinate per city.
        reps: dict[str, tuple[float, float]] = {}
        for s in sites:
            if s.city and s.lat is not None and s.lng is not None and s.city not in reps:
                reps[s.city] = (s.lat, s.lng)

        async with httpx.AsyncClient() as client:
            rain_by_city = {
                city: await _rain_48h(client, lat, lng) for city, (lat, lng) in reps.items()
            }

        now = datetime.now(UTC)
        for s in sites:
            rain = rain_by_city.get(s.city or "", s.rain_48h_mm or 0.0)
            days = 90.0 if s.last_verified_at is None else max(0, (now - s.last_verified_at).days)
            s.rain_48h_mm = rain
            s.need_score = scoring.need_score(
                float(days),
                cadence_days=float(s.cadence_days or 14),
                visit_share_90d=_visit_share(float(days)),
                rain_48h_mm=rain,
                expert_flag_open=s.expert_flag_open,
            )
        await session.commit()
        logger.info("recomputed need for %d sites across %d cities", len(sites), len(reps))

        # Reactivation (Track 5): if sites are due after heavy rain, send one
        # honest digest push to subscribers. Real event, no fake urgency.
        from app import push

        if push.enabled():
            after_rain = [
                s
                for s in sites
                if (s.rain_48h_mm or 0) >= scoring.RAIN_THRESHOLD_MM
                and (s.last_verified_at is None or (now - s.last_verified_at).days >= 3)
            ]
            if after_rain:
                n = len(after_rain)
                await push.broadcast(
                    session,
                    title="After the rain 🌧️",
                    body=f"{n} river{'s' if n != 1 else ''} need a look after recent rain.",
                    url="/missions",
                )
        return len(sites)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
