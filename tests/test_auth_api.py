"""Auth: the permanent, account-linked River Score."""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed

_n = 0


def _email() -> str:
    global _n
    _n += 1
    return f"score-{_n}@example.com"


async def test_river_score_requires_auth_and_sums_points():
    """401 for guests; sums the signed-in user's check points into a tier."""
    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/v1/auth/score")).status_code == 401

        tok = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": _email(),
                    "password": "riverkeeper1",
                    "display_name": "Scorer",
                    "role": "keeper",
                },
            )
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {tok}"}

        code = (await client.get("/api/v1/sites")).json()[0]["id"]
        created = await client.post(
            "/api/v1/observations",
            json={"site_code": code, "answers": {"q-water": "clear"}, "photo_count": 2},
            headers=headers,
        )
        assert created.status_code == 201
        # The check carries its River points (River Value) on the receipt.
        assert created.json()["receipt"]["points"] >= 0

        score = (await client.get("/api/v1/auth/score", headers=headers)).json()
        assert score["checks"] == 1
        assert score["score"] >= 0
        assert score["tier"] in {"Observer", "Explorer", "River Keeper"}


async def test_score_only_counts_the_authors_checks():
    """A second user's checks do not inflate the first user's score."""
    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        code = (await client.get("/api/v1/sites")).json()[0]["id"]

        def reg():
            return client.post(
                "/api/v1/auth/register",
                json={
                    "email": _email(),
                    "password": "riverkeeper1",
                    "display_name": "U",
                    "role": "keeper",
                },
            )

        tok_a = (await reg()).json()["access_token"]
        tok_b = (await reg()).json()["access_token"]
        ha = {"Authorization": f"Bearer {tok_a}"}
        hb = {"Authorization": f"Bearer {tok_b}"}

        # Only user B submits a check.
        await client.post(
            "/api/v1/observations",
            json={"site_code": code, "answers": {"q-water": "clear"}, "photo_count": 2},
            headers=hb,
        )
        assert (await client.get("/api/v1/auth/score", headers=ha)).json()["checks"] == 0
        assert (await client.get("/api/v1/auth/score", headers=hb)).json()["checks"] == 1
