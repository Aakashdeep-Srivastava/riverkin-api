"""Smoke tests for the HTTP app via httpx ASGI transport (no DB needed)."""

from __future__ import annotations

import httpx

from app.main import app


async def test_healthz_returns_ok():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_sites_list_returns_array():
    # /sites is now DB-backed and returns a JSON array of sites.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/sites")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_openapi_exposes_api_v1_routes():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/v1/sites" in paths
    assert "/api/v1/fhir/observations/{observation_id}" in paths
