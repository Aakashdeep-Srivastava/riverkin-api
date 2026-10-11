"""Integration tests for verify rounds + trust (Perfect 6 #4, needs DB)."""

from __future__ import annotations

import io

import httpx
import numpy as np
from PIL import Image

from app.main import app
from app.seed import seed


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _sharp_jpeg(seed_val: int) -> bytes:
    """High-frequency noise → passes the blur gate so the upload is accepted."""
    rng = np.random.default_rng(seed_val)
    buf = io.BytesIO()
    Image.fromarray(rng.integers(0, 255, size=(240, 320, 3)).astype("uint8")).save(
        buf, format="JPEG", quality=92
    )
    return buf.getvalue()


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
        # Card exposes the question + AI box (+ experiment arm), never gold
        # status, submitter or tally.
        assert set(card.keys()) == {
            "item_id",
            "observation_id",
            "site_name",
            "field_code",
            "question",
            "ai_box",
            "photo_url",
            "arm",
        }
        assert card["arm"] in {"assisted", "control"}
        # This submission carried no uploaded photo, so there is nothing to show.
        assert card["photo_url"] is None


async def test_verify_card_exposes_submitted_photo():
    """When a check carries a photo, the verify card points verifiers at it and
    that URL serves the processed image (so 'Does the photo support that?' can
    actually be answered)."""
    await seed()
    async with await _client() as client:
        code = (await client.get("/api/v1/sites")).json()[0]["id"]
        obs = (
            await client.post(
                "/api/v1/observations",
                json={"site_code": code, "answers": {"q-water": "clear"}, "photo_count": 0},
            )
        ).json()["id"]
        up = await client.post(
            f"/api/v1/observations/{obs}/photos",
            files={"file": ("a.jpg", _sharp_jpeg(11), "image/jpeg")},
        )
        assert up.status_code == 200

        cards = (await client.get("/api/v1/verify/next?n=10&voter_id=seer")).json()["cards"]
        card = next(c for c in cards if c["observation_id"] == obs)
        assert card["photo_url"] == f"/api/v1/observations/{obs}/photo"

        img = await client.get(card["photo_url"])
        assert img.status_code == 200
        assert img.headers["content-type"].startswith("image/")


async def test_verify_count_reflects_open_checks_and_excludes_voted():
    """/verify/count returns the real number of checks awaiting this voter, and
    drops to zero once they've voted on the only open check."""
    await seed()
    async with await _client() as client:
        # Baseline: no open checks for a fresh voter.
        start = (await client.get("/api/v1/verify/count?voter_id=counter")).json()["count"]
        await _submit(client)
        after = (await client.get("/api/v1/verify/count?voter_id=counter")).json()["count"]
        assert after == start + 1

        # Voting on every card for that check removes it from the voter's count.
        cards = (await client.get("/api/v1/verify/next?n=20&voter_id=counter")).json()["cards"]
        for c in cards:
            await client.post(
                f"/api/v1/verify/{c['item_id']}/vote",
                json={"answer": "yes", "voter_id": "counter"},
            )
        done = (await client.get("/api/v1/verify/count?voter_id=counter")).json()["count"]
        assert done == start


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
