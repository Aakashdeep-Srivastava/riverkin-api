"""Tests for the Azure Maps token endpoint via httpx ASGI transport.

These must never require real Azure credentials. With ``AZURE_MAPS_CLIENT_ID``
unset/empty (the CI condition) the endpoint fails fast with 503 before touching
any credential or network, so the test is fast and deterministic.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.main import app


async def test_maps_token_returns_503_when_client_id_unset(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_MAPS_CLIENT_ID", "")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/maps/token")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "maps token unavailable"}


async def test_static_map_returns_503_when_client_id_unset(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_MAPS_CLIENT_ID", "")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/maps/static", params={"lat": 40.2, "lng": -8.4})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "maps image unavailable"}


async def test_static_map_validates_coordinates(monkeypatch):
    # Out-of-range latitude is rejected by validation (422) before any auth.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/maps/static", params={"lat": 999, "lng": 0})
    assert resp.status_code == 422
