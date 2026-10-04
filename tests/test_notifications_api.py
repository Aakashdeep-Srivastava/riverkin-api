"""In-app notifications feed (Track 5 engagement)."""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed


async def test_notifications_are_real_and_well_formed():
    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/notifications")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) >= 1
        kinds = {i["kind"] for i in items}
        # Seeded state always yields at least a coverage milestone.
        assert "coverage" in kinds
        for i in items:
            assert i["id"] and i["title"] and i["body"]
            assert i["href"].startswith("/")
            assert i["kind"] in {"verified", "after-rain", "orphan", "coverage"}


async def test_notifications_city_filter():
    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/notifications?city=Coimbra")
        assert resp.status_code == 200
        assert any(n["kind"] == "coverage" for n in resp.json())
