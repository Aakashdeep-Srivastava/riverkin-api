"""RBAC enforcement on the privileged expert endpoints.

With settings.RBAC_ENFORCE (default True): no token → 401, wrong role → 403,
researcher → allowed. Flipping the flag off restores the open demo behaviour.
"""

from __future__ import annotations

import httpx

from app.config import settings
from app.main import app
from app.seed import seed


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _token(client: httpx.AsyncClient, role: str, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "pw-at-least-8", "display_name": "T", "role": role},
    )
    return resp.json()["access_token"]


async def test_expert_queue_requires_auth():
    await seed()
    async with await _client() as client:
        resp = await client.get("/api/v1/expert/queue")
        assert resp.status_code == 401
        assert resp.json()["detail"] == "sign in required"


async def test_expert_queue_forbidden_for_non_researcher():
    await seed()
    async with await _client() as client:
        token = await _token(client, "keeper", "keeper@example.com")
        resp = await client.get(
            "/api/v1/expert/queue", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403
        assert "researcher" in resp.json()["detail"]


async def test_expert_queue_allowed_for_researcher():
    await seed()
    async with await _client() as client:
        token = await _token(client, "researcher", "res@example.com")
        resp = await client.get(
            "/api/v1/expert/queue", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert "items" in resp.json()


async def test_review_forbidden_for_non_researcher():
    await seed()
    async with await _client() as client:
        token = await _token(client, "crew_lead", "lead@example.com")
        resp = await client.post(
            "/api/v1/expert/1/review",
            json={"decision": "confirm"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403


async def test_rbac_disabled_opens_endpoints(monkeypatch):
    await seed()
    monkeypatch.setattr(settings, "RBAC_ENFORCE", False)
    async with await _client() as client:
        # No token, but enforcement is off → the queue is reachable again.
        resp = await client.get("/api/v1/expert/queue")
        assert resp.status_code == 200
