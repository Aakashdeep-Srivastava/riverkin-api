"""Missions engine tests (FR11) — pure classification + HTTP integration."""

from __future__ import annotations

import httpx

from app import missions
from app.main import app
from app.seed import seed

# ---- pure classification (no DB) ------------------------------------------


def test_expert_flag_wins_over_everything():
    kind = missions.classify(
        days_unseen=40, rain_48h_mm=50.0, cadence_days=14, expert_flag_open=True
    )
    assert kind.title == "Flag Follow-up Check"


def test_rain_beats_orphan_and_cadence():
    kind = missions.classify(
        days_unseen=40, rain_48h_mm=25.0, cadence_days=14, expert_flag_open=False
    )
    assert kind.title == "After-the-Rain Check"
    assert "mm rain" in kind.window_label


def test_orphan_when_long_unseen_and_dry():
    kind = missions.classify(
        days_unseen=45, rain_48h_mm=0.0, cadence_days=14, expert_flag_open=False
    )
    assert kind.title == "Orphan-Site Check"
    assert kind.window_label == "Unseen 45 days"


def test_cadence_when_past_due_but_not_orphan():
    kind = missions.classify(
        days_unseen=16, rain_48h_mm=0.0, cadence_days=14, expert_flag_open=False
    )
    assert kind.title == "Cadence Check"


def test_monitoring_when_fresh():
    kind = missions.classify(
        days_unseen=3, rain_48h_mm=0.0, cadence_days=14, expert_flag_open=False
    )
    assert kind.title == "Monitoring Check"


def test_warrants_mission_rules():
    # Fresh, OK, dry → no mission.
    assert not missions.warrants_mission(
        attention="ok", days_unseen=2, rain_48h_mm=0.0, cadence_days=14, expert_flag_open=False
    )
    # Past cadence → mission even if band is ok.
    assert missions.warrants_mission(
        attention="ok", days_unseen=20, rain_48h_mm=0.0, cadence_days=14, expert_flag_open=False
    )
    # Any non-ok band → mission.
    assert missions.warrants_mission(
        attention="attention",
        days_unseen=1,
        rain_48h_mm=0.0,
        cadence_days=14,
        expert_flag_open=False,
    )
    # Fresh rain → mission.
    assert missions.warrants_mission(
        attention="ok", days_unseen=1, rain_48h_mm=30.0, cadence_days=14, expert_flag_open=False
    )


# ---- HTTP integration (needs DB + seed) -----------------------------------


async def _client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_list_missions_is_urgent_first():
    await seed()
    async with await _client() as client:
        res = await client.get("/api/v1/missions")
        assert res.status_code == 200
        items = res.json()
        assert len(items) > 0
        # Most-urgent first: need_score descends.
        scores = [m["need_score"] for m in items]
        assert scores == sorted(scores, reverse=True)
        # Every listed mission carries a title and a resolvable site.
        for m in items:
            assert m["title"]
            assert m["site_id"]
            assert m["attention"] in {"urgent", "attention", "monitoring", "ok"}


async def test_list_missions_city_filter():
    await seed()
    async with await _client() as client:
        items = (await client.get("/api/v1/missions", params={"city": "Coimbra"})).json()
        assert len(items) > 0
        assert all(m["city"] == "Coimbra" for m in items)


async def test_mission_brief_for_known_site():
    await seed()
    async with await _client() as client:
        code = (await client.get("/api/v1/sites")).json()[0]["id"]
        brief = (await client.get(f"/api/v1/missions/{code}")).json()
        assert brief["site_id"] == code
        assert brief["steps"] == ["Observe", "Photograph", "Verify"]
        assert brief["safety_line"]  # hard rule: safety copy on every brief
        assert brief["name"]
        assert brief["window_label"]


async def test_mission_brief_unknown_site_404():
    await seed()
    async with await _client() as client:
        res = await client.get("/api/v1/missions/NOPE-999")
        assert res.status_code == 404
