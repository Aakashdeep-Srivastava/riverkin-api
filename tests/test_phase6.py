"""Integration tests for FHIR export, expert queue/review, metrics (needs DB)."""

from __future__ import annotations

import httpx

from app.main import app
from app.seed import seed


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _submit(client: httpx.AsyncClient, answers: dict, feeling: str | None = None) -> int:
    code = (await client.get("/api/v1/sites")).json()[0]["id"]
    resp = await client.post(
        "/api/v1/observations",
        json={"site_code": code, "answers": answers, "feeling": feeling, "photo_count": 2},
    )
    return resp.json()["id"]


async def test_fhir_bundle_shape():
    await seed()
    async with await _client() as client:
        obs = await _submit(client, {"q-water": "clear", "q-foam": "none"}, feeling="calm")
        resp = await client.get(f"/api/v1/fhir/observations/{obs}")
        assert resp.status_code == 200
        bundle = resp.json()["bundle"]
        assert bundle["resourceType"] == "Bundle"
        assert bundle["type"] == "transaction"
        types = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert "Location" in types
        assert "Provenance" in types
        assert types.count("Observation") >= 2  # two fields + wellbeing
        # Real OAH code system is used on a field Observation.
        obs_entry = next(
            e for e in bundle["entry"] if e["resource"]["resourceType"] == "Observation"
        )
        systems = [c["system"] for c in obs_entry["resource"]["code"]["coding"]]
        assert any("temporarySystem-oah-eu" in s for s in systems)

        missing = await client.get("/api/v1/fhir/observations/999999")
        assert missing.status_code == 404


async def test_expert_queue_and_review_lifecycle():
    await seed()
    async with await _client() as client:
        obs = await _submit(client, {"q-water": "cloudy", "q-pipe": "yes"})  # pipe flag → expert
        queue = (await client.get("/api/v1/expert/queue")).json()["items"]
        assert obs in [i["observation_id"] for i in queue]

        confirm = await client.post(f"/api/v1/expert/{obs}/review", json={"decision": "confirm"})
        assert confirm.status_code == 200
        assert confirm.json()["status"] == "final"

        # No longer in the expert queue.
        queue2 = (await client.get("/api/v1/expert/queue")).json()["items"]
        assert obs not in [i["observation_id"] for i in queue2]

        bad = await client.post(f"/api/v1/expert/{obs}/review", json={"decision": "nope"})
        assert bad.status_code == 422
        missing = await client.post("/api/v1/expert/999999/review", json={"decision": "confirm"})
        assert missing.status_code == 404


async def test_expert_amend_updates_answer():
    await seed()
    async with await _client() as client:
        obs = await _submit(client, {"q-water": "cloudy", "q-pipe": "yes"})
        r = await client.post(
            f"/api/v1/expert/{obs}/review",
            json={"decision": "amend", "field_code": "q-water", "new_value": "clear"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "amended"


async def test_metrics():
    await seed()
    async with await _client() as client:
        m = (await client.get("/api/v1/metrics")).json()
        assert m["sites_total"] >= 106
        assert 0 <= m["coverage_fresh_pct"] <= 100
        assert m["sites_needing_attention"] >= 0
        assert "open_expert_reviews" in m
