"""Rate limiting (slowapi) — verify the per-IP limit trips with a 429.

The limiter is disabled under APP_ENV=test so the rest of the suite isn't
throttled; here we flip it on explicitly to exercise the behaviour.
"""

from __future__ import annotations

import httpx

from app.main import app
from app.ratelimit import AUTH_LIMIT, limiter


async def test_auth_rate_limit_returns_429(monkeypatch):
    monkeypatch.setattr(limiter, "enabled", True)
    limiter.reset()
    try:
        limit = int(AUTH_LIMIT.split("/")[0])  # "10/minute" -> 10
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            codes = []
            for _ in range(limit + 3):
                r = await client.post(
                    "/api/v1/auth/login",
                    json={"email": "nobody@example.com", "password": "wrong"},
                )
                codes.append(r.status_code)

        # The first `limit` are allowed (401 bad creds), the rest are throttled.
        assert codes.count(429) >= 1
        assert codes[0] == 401
        assert codes[-1] == 429
        # 429 carries a Retry-After so clients can back off.
        last = await httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ).post("/api/v1/auth/login", json={"email": "a@b.com", "password": "x"})
        assert last.status_code == 429
        assert "retry-after" in {k.lower() for k in last.headers}
    finally:
        limiter.reset()
