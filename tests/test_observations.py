"""Integration tests for the observation write path (Perfect 6 #3 / #5, needs DB)."""

from __future__ import annotations

import io

import httpx
import numpy as np
from PIL import Image

from app.main import app
from app.seed import seed


def _jpeg(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype("uint8")).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _sharp_jpeg(seed_val: int) -> bytes:
    """High-frequency noise → high Laplacian variance (passes the blur gate)."""
    rng = np.random.default_rng(seed_val)
    return _jpeg(rng.integers(0, 255, size=(240, 320, 3)))


def _blurry_jpeg() -> bytes:
    """Flat grey → ~0 Laplacian variance (fails the blur gate)."""
    return _jpeg(np.full((240, 320, 3), 128))


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _a_site_code(client: httpx.AsyncClient) -> str:
    resp = await client.get("/api/v1/sites")
    assert resp.status_code == 200
    return resp.json()[0]["id"]


async def test_create_observation_and_status():
    await seed()
    async with await _client() as client:
        code = await _a_site_code(client)
        resp = await client.post(
            "/api/v1/observations",
            json={
                "site_code": code,
                "answers": {
                    "q-water": "clear",
                    "q-litter": "some",
                    "q-foam": "none",
                    "q-flow": "normal",
                    "q-pipe": "no",
                },
                "feeling": "hopeful",
                "photo_count": 2,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["id"] > 0
        assert body["status"] == "in_verify"
        assert body["verify_item_count"] == 5  # one per answered field
        receipt = body["receipt"]
        assert receipt["fhir_id"].startswith("rk-")
        assert receipt["state"] == "In peer verification"
        assert receipt["sentinel_line"]

        # Status endpoint reflects the same observation.
        status = await client.get(f"/api/v1/observations/{body['id']}/status")
        assert status.status_code == 200
        sbody = status.json()
        assert sbody["id"] == body["id"]
        assert sbody["status"] == "in_verify"
        assert sbody["verifier_count"] == 0


async def test_pipe_flag_routes_to_expert():
    await seed()
    async with await _client() as client:
        code = await _a_site_code(client)
        resp = await client.post(
            "/api/v1/observations",
            json={
                "site_code": code,
                "answers": {"q-water": "cloudy", "q-pipe": "yes"},
                "photo_count": 2,
            },
        )
        assert resp.status_code == 201
        assert resp.json()["status"] == "expert"
        assert resp.json()["receipt"]["state"] == "Sent for expert review"


async def test_geofence_refusal():
    await seed()
    async with await _client() as client:
        code = await _a_site_code(client)
        resp = await client.post(
            "/api/v1/observations",
            json={
                "site_code": code,
                "answers": {"q-water": "clear"},
                "photo_count": 2,
                "lat": 0.0,
                "lng": 0.0,
            },
        )
        assert resp.status_code == 403
        assert resp.json()["detail"]["safety_reason"] == "outside_geofence"


async def test_unknown_site_and_observation_404():
    await seed()
    async with await _client() as client:
        bad = await client.post(
            "/api/v1/observations",
            json={"site_code": "NOPE-999", "answers": {}, "photo_count": 0},
        )
        assert bad.status_code == 404

        missing = await client.get("/api/v1/observations/999999/status")
        assert missing.status_code == 404


async def _new_obs(client: httpx.AsyncClient, code: str) -> int:
    resp = await client.post(
        "/api/v1/observations",
        json={"site_code": code, "answers": {"q-water": "clear"}, "photo_count": 0},
    )
    return resp.json()["id"]


async def test_photo_upload_blur_and_duplicate_gates():
    await seed()
    async with await _client() as client:
        code = await _a_site_code(client)

        # Blurry photo is rejected with a retake prompt.
        obs1 = await _new_obs(client, code)
        blurry = await client.post(
            f"/api/v1/observations/{obs1}/photos",
            files={"file": ("b.jpg", _blurry_jpeg(), "image/jpeg")},
        )
        assert blurry.status_code == 422
        assert blurry.json()["detail"]["reason"] == "retake_photo"

        # A sharp photo is accepted and processed (pHash returned).
        sharp = _sharp_jpeg(1)
        ok = await client.post(
            f"/api/v1/observations/{obs1}/photos",
            files={"file": ("a.jpg", sharp, "image/jpeg")},
        )
        assert ok.status_code == 200
        assert len(ok.json()["phash"]) >= 8

        # The same image reused for another obs at the same site is rejected.
        obs2 = await _new_obs(client, code)
        dup = await client.post(
            f"/api/v1/observations/{obs2}/photos",
            files={"file": ("a.jpg", sharp, "image/jpeg")},
        )
        assert dup.status_code == 409
        assert dup.json()["detail"]["reason"] == "duplicate_photo"


async def test_photo_analysis_authenticity_geotag_and_serving():
    await seed()
    async with await _client() as client:
        code = await _a_site_code(client)
        obs = await _new_obs(client, code)

        res = await client.post(
            f"/api/v1/observations/{obs}/photos",
            files={"file": ("a.jpg", _sharp_jpeg(7), "image/jpeg")},
            data={"kind": "upstream", "captured_live": "true"},
        )
        assert res.status_code == 200
        analysis = res.json()["analysis"]
        assert analysis["summary"]
        assert 0 <= analysis["authenticity"] <= 100
        assert analysis["captured_live"] is True
        # A live, novel capture scores well.
        assert analysis["authenticity"] >= 60
        assert analysis["geotag"] and analysis["geotag"]["label"].startswith("Within 150 m")

        # The receipt (via status) now carries the photo block.
        status = (await client.get(f"/api/v1/observations/{obs}/status")).json()
        photo = status["receipt"]["photo"]
        assert photo is not None
        assert photo["url"] == f"/api/v1/observations/{obs}/photo"
        assert photo["captured_live"] is True
        assert photo["geotag_label"].startswith("Within 150 m")

        # The processed image is served back as JPEG.
        img = await client.get(f"/api/v1/observations/{obs}/photo")
        assert img.status_code == 200
        assert img.headers["content-type"] == "image/jpeg"
        assert len(img.content) > 0
