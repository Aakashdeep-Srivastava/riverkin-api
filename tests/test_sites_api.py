"""Integration tests for the sites API against the seeded OAH data (needs DB)."""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed


async def test_seed_and_list_sites():
    n = await seed()
    assert n == 106

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/sites")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 106

        # Sorted most-urgent (highest need) first.
        needs = [s["need_score"] for s in data]
        assert needs == sorted(needs, reverse=True)

        top = data[0]
        assert top["attention"] in {"urgent", "attention", "monitoring", "ok"}
        assert top["color"] in {"red", "amber", "cyan", "grey"}
        assert top["lat"] is not None and top["id"]
        assert top["simulated"] is True

        # Single site + 404.
        one = await client.get(f"/api/v1/sites/{top['id']}")
        assert one.status_code == 200
        assert one.json()["id"] == top["id"]

        missing = await client.get("/api/v1/sites/NOPE-999")
        assert missing.status_code == 404


async def test_seed_is_idempotent():
    assert await seed() == 106
    assert await seed() == 106  # re-running does not duplicate rows
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/sites?city=Coimbra")
        assert resp.status_code == 200
        assert len(resp.json()) == 20  # Coimbra has 20 real OAH sites
