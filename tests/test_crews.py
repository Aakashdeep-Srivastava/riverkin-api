"""Integration tests for crews + timeline (later layer, needs DB)."""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_create_crew_member_adoption_and_view():
    await seed()
    async with await _client() as client:
        code = (await client.get("/api/v1/sites")).json()[0]["id"]
        crew = (
            await client.post(
                "/api/v1/crews",
                json={"name": "Crew Coselhas", "city": "Coimbra", "is_minor_crew": True},
            )
        ).json()
        cid = crew["id"]

        await client.post(
            f"/api/v1/crews/{cid}/members",
            json={"handle": "Scout 3", "role_this_week": "scout"},
        )
        adopt = await client.post(f"/api/v1/crews/{cid}/adoptions", json={"site_code": code})
        assert adopt.status_code == 201
        await client.post(f"/api/v1/crews/{cid}/checkins")

        view = (await client.get(f"/api/v1/crews/{cid}")).json()
        assert view["name"] == "Crew Coselhas"
        assert view["is_minor_crew"] is True
        assert len(view["members"]) == 1 and view["members"][0]["handle"] == "Scout 3"
        assert len(view["adopted"]) == 1
        assert 0 <= view["coverage_pct"] <= 100
        assert view["checkin_active"] is True


async def test_adoption_cap_of_three():
    await seed()
    async with await _client() as client:
        codes = [s["id"] for s in (await client.get("/api/v1/sites")).json()[:4]]
        cid = (await client.post("/api/v1/crews", json={"name": "Cap crew"})).json()["id"]
        for code in codes[:3]:
            r = await client.post(f"/api/v1/crews/{cid}/adoptions", json={"site_code": code})
            assert r.status_code == 201
        fourth = await client.post(f"/api/v1/crews/{cid}/adoptions", json={"site_code": codes[3]})
        assert fourth.status_code == 409


async def test_crew_404_and_bad_site():
    await seed()
    async with await _client() as client:
        missing = await client.get("/api/v1/crews/999999")
        assert missing.status_code == 404
        cid = (await client.post("/api/v1/crews", json={"name": "X"})).json()["id"]
        bad = await client.post(f"/api/v1/crews/{cid}/adoptions", json={"site_code": "NOPE-999"})
        assert bad.status_code == 404


async def test_timeline_includes_submitted_observations():
    await seed()
    async with await _client() as client:
        code = (await client.get("/api/v1/sites")).json()[0]["id"]
        await client.post(
            "/api/v1/observations",
            json={"site_code": code, "answers": {"q-water": "clear"}, "photo_count": 2},
        )
        tl = (await client.get(f"/api/v1/sites/{code}/timeline")).json()
        assert tl["site_id"] == code
        assert any(e["kind"] == "check" for e in tl["entries"])
