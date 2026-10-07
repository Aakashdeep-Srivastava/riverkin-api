"""External ecological signals — GBIF biodiversity + GloFAS river discharge.

Both are *real, keyless* open-data enrichments. They are fetched by the scheduled
job (``app/jobs/scheduled.py``) and cached verbatim on the ``Site`` row
(``biodiversity`` / ``discharge`` JSONB columns) exactly the way ``rain_48h_mm`` is
denormalised. Request-time endpoints never call out — they serve the cached
snapshot, so ``GET /sites`` stays fast and we never hammer an upstream per view.

Every fetch degrades gracefully (returns ``None`` on any error, timeout or empty
upstream) so a slow or rate-limited source can never break the job or a response.
No API keys are required for either source.

Sources & attribution (surfaced in the API response and the UI):
- GBIF occurrence API — "Powered by GBIF (GBIF.org)". Mixed per-dataset licences.
- Open-Meteo Flood API / GloFAS — "Flood data by Open-Meteo.com (CC-BY 4.0);
  source GloFAS/Copernicus (ECMWF)".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

logger = logging.getLogger("app.signals")

# Polite descriptive UA (GBIF is lenient; some open endpoints 406 a bare client).
USER_AGENT = "RiverKin/1.0 (+https://riverkin.online; OneAquaHealth citizen science)"

GBIF_SEARCH_URL = "https://api.gbif.org/v1/occurrence/search"
GLOFAS_FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"

GBIF_ATTRIBUTION = "Powered by GBIF (GBIF.org)"
GLOFAS_ATTRIBUTION = (
    "Flood data by Open-Meteo.com (CC-BY 4.0); source GloFAS/Copernicus (ECMWF)"
)

# Freshwater bioindicator taxa (GBIF backbone keys). Restricting to these keeps
# the signal to clean-water indicators rather than all biodiversity (which would
# be dominated by terrestrial records). EPT = the classic macroinvertebrate
# bioindicator orders; amphibians are a sensitive riparian indicator.
#   1225 Ephemeroptera (mayflies) · 787 Plecoptera (stoneflies)
#   1003 Trichoptera (caddisflies) · 131 Amphibia
GBIF_BIOINDICATOR_TAXA = (1225, 787, 1003, 131)
GBIF_RADIUS_KM = 5

# Discharge history window for the site sparkline.
GLOFAS_PAST_DAYS = 30
GLOFAS_FORECAST_DAYS = 7


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def fetch_biodiversity(
    client: httpx.AsyncClient, lat: float, lng: float
) -> dict | None:
    """Freshwater bioindicator richness within 5 km of a point, via GBIF.

    One keyless call ORs the EPT + Amphibia taxon keys and facets on species, so
    we get both the total occurrence ``count`` and the distinct-species richness
    (``len(facet counts)``) in a single request. Returns ``None`` on any failure
    or when there are zero records (honest absence rather than a fake zero).
    """
    try:
        resp = await client.get(
            GBIF_SEARCH_URL,
            params={
                "taxonKey": list(GBIF_BIOINDICATOR_TAXA),  # repeated → OR
                "geoDistance": f"{lat},{lng},{GBIF_RADIUS_KM}km",
                "hasCoordinate": "true",
                "limit": 0,
                "facet": "speciesKey",
                "facetLimit": 300,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
        )
        resp.raise_for_status()
        data = resp.json()
        occurrences = int(data.get("count", 0) or 0)
        facets = data.get("facets", []) or []
        counts = facets[0].get("counts", []) if facets else []
        richness = len(counts)
        if occurrences == 0 and richness == 0:
            return None
        return {
            "occurrences": occurrences,
            "species_richness": richness,
            "radius_km": GBIF_RADIUS_KM,
            "indicator": "EPT (mayflies, stoneflies, caddisflies) + amphibians",
            "sampled_at": _now_iso(),
            "source": "GBIF",
            "attribution": GBIF_ATTRIBUTION,
        }
    except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
        logger.warning("GBIF fetch failed for (%s,%s): %s", lat, lng, exc)
        return None


async def fetch_discharge(
    client: httpx.AsyncClient, lat: float, lng: float
) -> dict | None:
    """River discharge (m³/s) at a point, via Open-Meteo Flood / GloFAS.

    Returns the latest value, a 30-day mean, and a daily series for a sparkline.
    The GloFAS grid is ~5 km, so small streams can snap to a neighbouring cell or
    have no modelled discharge — in that case we return ``None`` rather than a
    misleading zero.
    """
    try:
        resp = await client.get(
            GLOFAS_FLOOD_URL,
            params={
                "latitude": lat,
                "longitude": lng,
                "daily": "river_discharge",
                "past_days": GLOFAS_PAST_DAYS,
                "forecast_days": GLOFAS_FORECAST_DAYS,
                "timezone": "UTC",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
        )
        resp.raise_for_status()
        daily = resp.json().get("daily", {}) or {}
        times = daily.get("time", []) or []
        values = daily.get("river_discharge", []) or []
        series = [
            {"date": t, "value": round(float(v), 2)}
            for t, v in zip(times, values, strict=False)
            if v is not None
        ]
        if not series:
            return None
        nums = [p["value"] for p in series]
        latest = series[-1]
        return {
            "latest_m3s": latest["value"],
            "latest_date": latest["date"],
            "mean_30d_m3s": round(sum(nums) / len(nums), 2),
            "series": series,
            "grid_note": "GloFAS ~5 km grid — approximate for small streams",
            "sampled_at": _now_iso(),
            "source": "GloFAS/Copernicus via Open-Meteo",
            "attribution": GLOFAS_ATTRIBUTION,
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("GloFAS fetch failed for (%s,%s): %s", lat, lng, exc)
        return None
