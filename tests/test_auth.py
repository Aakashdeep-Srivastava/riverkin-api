"""Integration tests for adult-account auth (needs DB)."""

from __future__ import annotations

import httpx

from app.main import app


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


REG = {
    "email": "kari@example.com",
    "password": "riverkeeper1",
    "display_name": "Kari",
    "role": "keeper",
}


async def test_register_login_me_flow():
    async with await _client() as client:
        r = await client.post("/api/v1/auth/register", json=REG)
        assert r.status_code == 201
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user"]["email"] == "kari@example.com"
        assert body["user"]["role"] == "keeper"
        token = body["access_token"]

        # /me with the bearer token.
        me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["authenticated"] is True
        assert me.json()["user"]["display_name"] == "Kari"

        # /me without a token.
        anon = await client.get("/api/v1/auth/me")
        assert anon.json()["authenticated"] is False

        # Login with the same credentials.
        login = await client.post(
            "/api/v1/auth/login", json={"email": "kari@example.com", "password": "riverkeeper1"}
        )
        assert login.status_code == 200
        assert login.json()["access_token"]


async def test_duplicate_email_rejected():
    async with await _client() as client:
        assert (await client.post("/api/v1/auth/register", json=REG)).status_code == 201
        dup = await client.post("/api/v1/auth/register", json=REG)
        assert dup.status_code == 409


async def test_bad_login_and_invalid_role():
    async with await _client() as client:
        await client.post("/api/v1/auth/register", json=REG)
        bad = await client.post(
            "/api/v1/auth/login", json={"email": "kari@example.com", "password": "wrongpass1"}
        )
        assert bad.status_code == 401

        missing = await client.post(
            "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
        )
        assert missing.status_code == 401

        bad_role = await client.post(
            "/api/v1/auth/register",
            json={**REG, "email": "x@example.com", "role": "admin"},
        )
        assert bad_role.status_code == 422


async def test_short_password_rejected():
    async with await _client() as client:
        r = await client.post(
            "/api/v1/auth/register",
            json={**REG, "email": "y@example.com", "password": "short"},
        )
        assert r.status_code == 422
