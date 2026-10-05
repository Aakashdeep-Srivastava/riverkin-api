"""Tests for the Strava OAuth endpoints via httpx ASGI transport.

These never require real Strava credentials: with STRAVA_CLIENT_ID/SECRET unset
(the CI condition) the feature reports disabled and the connect redirect 404s,
and the authed endpoints reject anonymous callers.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.main import app


async def test_strava_config_disabled_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "STRAVA_CLIENT_ID", "")
    monkeypatch.setattr(settings, "STRAVA_CLIENT_SECRET", "")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/strava/config")
    assert resp.status_code == 200
    assert resp.json() == {"enabled": False}


async def test_strava_connect_404_when_unconfigured(monkeypatch):
    monkeypatch.setattr(settings, "STRAVA_CLIENT_ID", "")
    monkeypatch.setattr(settings, "STRAVA_CLIENT_SECRET", "")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/strava/connect", params={"ticket": "x"})
    assert resp.status_code == 404


async def test_strava_status_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/strava/status")
    assert resp.status_code == 401


async def test_strava_activities_requires_auth():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/strava/activities")
    assert resp.status_code == 401
