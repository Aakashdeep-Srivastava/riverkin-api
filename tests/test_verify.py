"""Integration tests for verify rounds + trust (Perfect 6 #4, needs DB)."""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _submit(client: httpx.AsyncClient) -> int:
    code = (await client.get("/api/v1/sites")).json()[0]["id"]
    resp = await client.post(
        "/api/v1/observations",
        json={
            "site_code": code,
            "answers": {
                "q-water": "clear",
                "q-litter": "none",
                "q-foam": "none",
                "q-flow": "normal",
                "q-pipe": "no",
            },
            "photo_count": 2,
        },
    )
    return resp.json()["id"]


async def test_next_returns_cards_without_gold_or_submitter():
    await seed()
    async with await _client() as client:
        await _submit(client)
        resp = await client.get("/api/v1/verify/next?n=5&voter_id=kari")
        assert resp.status_code == 200
        cards = resp.json()["cards"]
        assert len(cards) >= 1
        card = cards[0]
        # Card exposes the question + AI box, never gold status, submitter or tally.
        assert set(card.keys()) == {
            "item_id",
            "observation_id",
            "site_name",
            "field_code",
            "question",
            "ai_box",
        }


async def test_three_yes_votes_reach_community_verified():
    await seed()
    async with await _client() as client:
        await _submit(client)
        item = (await client.get("/api/v1/verify/next?n=1&voter_id=picker")).json()["cards"][0][
            "item_id"
        ]
        last = None
        for voter in ("a", "b", "c"):
            r = await client.post(
                f"/api/v1/verify/{item}/vote",
                json={"answer": "yes", "ms_taken": 1200, "voter_id": voter},
            )
            assert r.status_code == 200
            last = r.json()
        assert last["observation_status"] == "community-verified"
        assert last["trust"] >= 0.8


async def test_voter_does_not_see_item_twice():
    await seed()
    async with await _client() as client:
        await _submit(client)
        first = (await client.get("/api/v1/verify/next?n=1&voter_id=repeat")).json()["cards"][0][
            "item_id"
        ]
        await client.post(
            f"/api/v1/verify/{first}/vote",
            json={"answer": "yes", "voter_id": "repeat"},
        )
        remaining = (await client.get("/api/v1/verify/next?n=10&voter_id=repeat")).json()["cards"]
        assert first not in [c["item_id"] for c in remaining]


async def test_invalid_answer_and_missing_item():
    await seed()
    async with await _client() as client:
        await _submit(client)
        cards = (await client.get("/api/v1/verify/next?n=1&voter_id=x")).json()["cards"]
        item = cards[0]["item_id"]
        bad = await client.post(f"/api/v1/verify/{item}/vote", json={"answer": "maybe"})
        assert bad.status_code == 422
        missing = await client.post("/api/v1/verify/999999/vote", json={"answer": "yes"})
        assert missing.status_code == 404
