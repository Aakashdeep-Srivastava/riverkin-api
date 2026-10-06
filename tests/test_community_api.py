"""Community endpoints (Track 5): city standings + derived challenges."""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed


async def test_standings_ranks_five_cities():
    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/community/standings")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) >= 5  # the five OAH cities + any extra regions
        # Ranked, contiguous, and coverage is non-increasing.
        assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
        covs = [r["coverage_pct"] for r in rows]
        assert covs == sorted(covs, reverse=True)
        for r in rows:
            assert r["sites_fresh"] <= r["sites_total"]
            assert 0 <= r["coverage_pct"] <= 100


async def test_challenges_are_real_counts():
    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/community/challenges?city=Coimbra")
        assert resp.status_code == 200
        for ch in resp.json():
            assert ch["target"] >= 1
            assert ch["kind"] in {"after-rain", "orphan", "coverage"}
            assert ch["city"] == "Coimbra"
