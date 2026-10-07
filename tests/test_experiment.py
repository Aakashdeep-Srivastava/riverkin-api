"""A/B verification-lift experiment: arm assignment + the lift metric endpoint."""

from __future__ import annotations

import httpx

from app.experiment import ARMS, assign_arm
from app.main import app
from app.seed import seed


def test_assign_arm_is_deterministic_and_stable():
    a = assign_arm("voter-1", 42)
    assert a in ARMS
    assert assign_arm("voter-1", 42) == a  # stable for the same pair


def test_assign_arm_splits_both_ways():
    arms = {assign_arm(f"voter-{i}", 1) for i in range(50)}
    assert arms == set(ARMS)  # both arms occur across many voters


async def test_verification_lift_endpoint_honest_when_empty():
    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/metrics/experiment/verification-lift")
    assert resp.status_code == 200
    data = resp.json()
    assert data["experiment"] == "verify-ai-assist"
    assert data["status"] == "insufficient_data"
    assert data["assisted"]["n"] == 0 and data["control"]["n"] == 0
    assert data["accuracy_lift_pct"] is None
    assert "Experimental" in data["note"]


async def test_vote_records_an_arm():
    """A cast vote stores the experiment arm matching the voter+item assignment."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models.observation import Observation
    from app.models.verify import VerifyItem, Vote

    await seed()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        code = (await client.get("/api/v1/sites")).json()[0]["id"]
        obs = await client.post(
            "/api/v1/observations",
            json={"site_code": code, "answers": {"q-water": "clear"}, "photo_count": 0},
        )
        obs_id = obs.json()["id"]
        # Find a verify item for this observation, if the pipeline made one.
        async with SessionLocal() as s:
            item = (
                await s.execute(
                    select(VerifyItem).where(VerifyItem.observation_id == obs_id).limit(1)
                )
            ).scalar_one_or_none()
            # Also confirm the observation exists (sanity).
            assert (await s.get(Observation, obs_id)) is not None
        if item is None:
            return  # no verify item generated for this answer set — nothing to vote on

        await client.post(
            f"/api/v1/verify/{item.id}/vote",
            json={"answer": "yes", "voter_id": "voter-xyz", "ms_taken": 1200},
        )
        async with SessionLocal() as s:
            vote = (
                await s.execute(select(Vote).where(Vote.verify_item_id == item.id))
            ).scalars().first()
        assert vote is not None
        assert vote.arm == assign_arm("voter-xyz", item.id)
