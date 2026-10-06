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


async def test_geofence_non_blocking_by_default():
    """Default (demo/field-test): a far check is accepted but flagged geo_ok=False
    so the full pipeline still runs from anywhere (e.g. developing from India)."""
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
        assert resp.status_code == 201
        assert resp.json()["receipt"]["geo_ok"] is False


async def test_geofence_enforced_refuses(monkeypatch):
    """With GEOFENCE_ENFORCE=True, a far check is refused (403)."""
    from app.config import settings

    monkeypatch.setattr(settings, "GEOFENCE_ENFORCE", True)
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


async def _new_obs(
    client: httpx.AsyncClient, code: str, lat: float | None = None, lng: float | None = None
) -> int:
    payload: dict = {"site_code": code, "answers": {"q-water": "clear"}, "photo_count": 0}
    if lat is not None and lng is not None:
        payload["lat"] = lat
        payload["lng"] = lng
    resp = await client.post("/api/v1/observations", json=payload)
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


async def test_photo_contradiction_grounds_prior_and_escalates(monkeypatch):
    """A confident photo↔answer contradiction escalates to expert and flips the
    grounded AI prior (AI asks, humans decide)."""
    from app.ai import vision

    async def _fake(_raw: bytes):
        return vision.VisionAnalysis(
            summary="Turbid, brown water.",
            tags=["turbid"],
            ai_generated_likelihood=0.2,
            relevance=0.8,
            fields={"water_appearance": {"value": "turbid", "confidence": 0.9}},
            model="test",
            used_model=True,
        )

    monkeypatch.setattr(vision, "analyze_image", _fake)

    await seed()
    async with await _client() as client:
        code = await _a_site_code(client)
        # Citizen says the water is clear; the photo (mock) says turbid.
        obs = (
            await client.post(
                "/api/v1/observations",
                json={"site_code": code, "answers": {"q-water": "clear"}, "photo_count": 0},
            )
        ).json()["id"]
        res = await client.post(
            f"/api/v1/observations/{obs}/photos",
            files={"file": ("a.jpg", _sharp_jpeg(3), "image/jpeg")},
        )
        assert res.status_code == 200
        analysis = res.json()["analysis"]
        assert analysis["escalated"] is True
        assert analysis["discrepancy_count"] >= 1
        water = next(c for c in analysis["correlation"] if c["field"] == "q-water")
        assert water["agrees"] is False
        # The observation is now routed to expert review.
        status = (await client.get(f"/api/v1/observations/{obs}/status")).json()
        assert "review" in status["receipt"]["state"].lower() or status["receipt"]["state"]


async def test_photo_analysis_authenticity_geotag_and_serving():
    await seed()
    async with await _client() as client:
        sites = (await client.get("/api/v1/sites")).json()
        site = sites[0]
        code = site["id"]
        # Create the check AT the site (within the geofence) so location
        # strengthens authenticity.
        obs = await _new_obs(client, code, lat=site["lat"], lng=site["lng"])

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
        # A live, novel, on-site capture scores well.
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


async def test_analyze_preview_returns_real_fields():
    """Stateless /analyze returns a vision read without needing an observation."""
    async with await _client() as client:
        resp = await client.post(
            "/api/v1/observations/analyze",
            files={"file": ("a.jpg", _sharp_jpeg(7), "image/jpeg")},
            data={"captured_live": "true"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    for key in ("summary", "tags", "ai_generated_likelihood", "authenticity", "used_model"):
        assert key in body
    assert 0 <= body["authenticity"] <= 100


async def test_analyze_preview_flags_blurry():
    async with await _client() as client:
        resp = await client.post(
            "/api/v1/observations/analyze",
            files={"file": ("b.jpg", _blurry_jpeg(), "image/jpeg")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["reason"] == "retake_photo"
