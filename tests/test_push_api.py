"""Web Push subscription endpoints."""

from __future__ import annotations

import httpx

from app.main import app


async def test_vapid_public_and_subscribe_roundtrip():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Public key endpoint always responds (empty when push disabled).
        vp = await client.get("/api/v1/push/vapid-public")
        assert vp.status_code == 200 and "key" in vp.json()

        sub = {
            "endpoint": "https://push.example.com/abc123",
            "keys": {"p256dh": "BPk...", "auth": "xyz"},
        }
        r = await client.post("/api/v1/push/subscribe", json=sub)
        assert r.status_code == 201 and r.json()["subscribed"] is True
        # Idempotent: re-subscribing the same endpoint updates, not duplicates.
        r2 = await client.post("/api/v1/push/subscribe", json=sub)
        assert r2.status_code == 201

        u = await client.post(
            "/api/v1/push/unsubscribe", json={"endpoint": sub["endpoint"]}
        )
        assert u.status_code == 200 and u.json()["unsubscribed"] is True
