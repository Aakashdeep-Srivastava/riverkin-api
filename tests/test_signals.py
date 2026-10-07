"""Unit tests for the GBIF + GloFAS signal fetchers and the refresh guard.

No network: every outbound call is served by an httpx.MockTransport, matching the
suite's in-process rule. Covers happy-path parsing, honest-absence (None) on empty
or failed upstreams, and the 24 h staleness guard in refresh_signals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from app import signals
from app.jobs import scheduled
from app.main import app
from app.models.site import Site
from app.seed import seed


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- GBIF


async def test_gbif_parses_count_and_richness():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "api.gbif.org" in str(request.url)
        # Repeated taxonKey (OR) + 5 km geoDistance must be present.
        assert request.url.params.get_list("taxonKey") == ["1225", "787", "1003", "131"]
        assert request.url.params.get("geoDistance", "").endswith(",5km")
        return httpx.Response(
            200,
            json={
                "count": 42,
                "facets": [
                    {"field": "SPECIES_KEY", "counts": [{"name": "1", "count": 9}] * 7}
                ],
            },
        )

    async with _client(handler) as client:
        out = await signals.fetch_biodiversity(client, 40.2, -8.4)
    assert out is not None
    assert out["occurrences"] == 42
    assert out["species_richness"] == 7
    assert out["radius_km"] == 5
    assert out["attribution"] == signals.GBIF_ATTRIBUTION
    assert out["sampled_at"]


async def test_gbif_empty_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"count": 0, "facets": []})

    async with _client(handler) as client:
        assert await signals.fetch_biodiversity(client, 0.0, 0.0) is None


async def test_gbif_http_error_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream down")

    async with _client(handler) as client:
        assert await signals.fetch_biodiversity(client, 1.0, 1.0) is None


# -------------------------------------------------------------------------- GloFAS


async def test_glofas_parses_series_latest_mean():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "flood-api.open-meteo.com" in str(request.url)
        return httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-10-01", "2026-10-02", "2026-10-03"],
                    "river_discharge": [10.0, None, 20.0],
                }
            },
        )

    async with _client(handler) as client:
        out = await signals.fetch_discharge(client, 40.2, -8.4)
    assert out is not None
    assert out["latest_m3s"] == 20.0
    assert out["latest_date"] == "2026-10-03"
    assert out["mean_30d_m3s"] == 15.0  # None dropped: mean(10, 20)
    assert [p["date"] for p in out["series"]] == ["2026-10-01", "2026-10-03"]
    assert out["attribution"] == signals.GLOFAS_ATTRIBUTION


async def test_glofas_all_null_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"daily": {"time": ["2026-10-01"], "river_discharge": [None]}}
        )

    async with _client(handler) as client:
        assert await signals.fetch_discharge(client, 0.0, 0.0) is None


# -------------------------------------------------------------- staleness + refresh


def test_signal_stale_guard():
    assert scheduled._signal_stale(None) is True
    assert scheduled._signal_stale({}) is True
    assert scheduled._signal_stale({"sampled_at": "not-a-date"}) is True
    fresh = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    old = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    assert scheduled._signal_stale({"sampled_at": fresh}) is False
    assert scheduled._signal_stale({"sampled_at": old}) is True


async def test_refresh_signals_skips_fresh_and_fills_stale():
    calls = {"gbif": 0, "glofas": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "gbif.org" in str(request.url):
            calls["gbif"] += 1
            return httpx.Response(
                200,
                json={"count": 5, "facets": [{"counts": [{"name": "1", "count": 5}]}]},
            )
        calls["glofas"] += 1
        return httpx.Response(
            200,
            json={"daily": {"time": ["2026-10-03"], "river_discharge": [12.3]}},
        )

    fresh_bio = {"sampled_at": datetime.now(UTC).isoformat(), "occurrences": 1}
    stale = Site(lat=40.2, lng=-8.4, name="stale", external_id="S1")
    partial = Site(
        lat=41.0, lng=-8.0, name="partial", external_id="S2", biodiversity=fresh_bio
    )
    nocoords = Site(lat=None, lng=None, name="nocoords", external_id="S3")

    async with _client(handler) as client:
        updated = await scheduled.refresh_signals([stale, partial, nocoords], client)

    # stale: both filled. partial: biodiversity fresh (skipped), discharge filled.
    assert updated == 2
    assert stale.biodiversity["occurrences"] == 5
    assert stale.discharge["latest_m3s"] == 12.3
    assert partial.biodiversity is fresh_bio  # untouched
    assert partial.discharge["latest_m3s"] == 12.3
    assert nocoords.biodiversity is None  # no coords → skipped entirely
    # GBIF called once (stale only); GloFAS twice (stale + partial).
    assert calls == {"gbif": 1, "glofas": 2}


async def test_sites_endpoint_surfaces_bundled_signals():
    """The seeded bundle (data/site_signals.json) surfaces on GET /sites."""
    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/sites")
        assert resp.status_code == 200
        data = resp.json()
        # At least some sites carry real biodiversity + discharge from the bundle.
        with_bio = [s for s in data if s.get("biodiversity")]
        with_dis = [s for s in data if s.get("discharge")]
        assert with_bio, "expected bundled GBIF biodiversity on some sites"
        assert with_dis, "expected bundled GloFAS discharge on some sites"
        bio = with_bio[0]["biodiversity"]
        assert "species_richness" in bio and "attribution" in bio
        dis = with_dis[0]["discharge"]
        assert "latest_m3s" in dis and dis["series"]
