"""Integration tests for the community challenges API (needs DB).

Covers the real growth loop: list with live joined counts, idempotent join,
community-credit computation, and pseudonymous referral crediting — all kept in
the COMMUNITY ledger, never touching scientific trust.
"""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed_challenges


async def test_challenges_list_and_join_and_referral():
    await seed_challenges()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # --- list ---
        r = await client.get("/api/v1/challenges")
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 5
        run = next(c for c in items if c["id"] == "run-for-the-river")
        assert run["featured"] is True
        assert run["joined"] == 21  # base_joined seed, no real participants yet

        # status filter
        live = (await client.get("/api/v1/challenges?status=live")).json()
        assert all(c["status"] == "live" for c in live)

        # unknown detail -> 404
        assert (await client.get("/api/v1/challenges/does-not-exist")).status_code == 404

        # --- join increments the live count + awards credits ---
        r = await client.post(
            "/api/v1/challenges/run-for-the-river/join", json={"key": "RK-AAAA"}
        )
        assert r.status_code == 200
        res = r.json()
        assert res["challenge"]["joined"] == 22  # 21 base + 1 real
        assert res["profile"]["missions"] == 1
        assert res["profile"]["credits"] == 30  # round(120 * 0.25)
        assert "run-for-the-river" in res["profile"]["joined_ids"]

        # idempotent — joining again does not double-count
        r = await client.post(
            "/api/v1/challenges/run-for-the-river/join", json={"key": "RK-AAAA"}
        )
        assert r.json()["challenge"]["joined"] == 22

        # --- referral: attach on landing, credit when the friend joins ---
        assert (
            await client.post(
                "/api/v1/referrals", json={"referrer": "RK-AAAA", "referred": "RK-BBBB"}
            )
        ).status_code == 200
        # before the friend joins, the referrer is not yet credited
        prof = (await client.get("/api/v1/community/profile?key=RK-AAAA")).json()
        assert prof["referrals"] == 0

        await client.post(
            "/api/v1/challenges/after-rain-check/join", json={"key": "RK-BBBB"}
        )
        prof = (await client.get("/api/v1/community/profile?key=RK-AAAA")).json()
        assert prof["referrals"] == 1
        assert prof["credits"] == 80  # 30 join + 50 referral bonus

        # --- no self-referral ---
        await client.post(
            "/api/v1/referrals", json={"referrer": "RK-CCCC", "referred": "RK-CCCC"}
        )
        await client.post(
            "/api/v1/challenges/biodiversity-walk/join", json={"key": "RK-CCCC"}
        )
        prof_c = (await client.get("/api/v1/community/profile?key=RK-CCCC")).json()
        assert prof_c["referrals"] == 0
        assert prof_c["rivers_helped"] == 1
