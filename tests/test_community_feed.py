"""Community feed: post + list (needs DB)."""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_post_and_list_community_feed():
    await seed()
    async with await _client() as client:
        code = (await client.get("/api/v1/sites")).json()[0]["id"]
        r = await client.post(
            "/api/v1/community/posts",
            json={
                "author_key": "RK-TEST",
                "author_name": "Kari",
                "body": "First check done — the water looked clear today!",
                "site_code": code,
            },
        )
        assert r.status_code == 201
        created = r.json()
        assert created["author_name"] == "Kari"
        assert created["site_code"] == code
        assert "clear today" in created["body"]

        feed = (await client.get("/api/v1/community/posts?limit=10")).json()
        assert any(p["id"] == created["id"] for p in feed)
        # Newest first.
        assert feed[0]["id"] == created["id"]


async def test_empty_post_rejected():
    await seed()
    async with await _client() as client:
        r = await client.post(
            "/api/v1/community/posts",
            json={"author_key": "RK-X", "body": "   "},
        )
        assert r.status_code == 422
