"""Pure validation of the bundled OAH data files (no DB)."""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

OAH_CITIES = {"Coimbra", "Toulouse", "Benevento", "Ghent", "Oslo"}


def test_oah_sites_file_shape():
    data = json.loads((DATA / "oah_sites.json").read_text(encoding="utf-8"))
    assert data["schema"] == "riverkin.oah_sites.v2"
    assert data["count"] == 106
    sites = data["sites"]
    assert len(sites) == 106
    codes = {s["oah_code"] for s in sites}
    assert len(codes) == 106  # unique codes
    cities = {s["city"] for s in sites}
    assert cities == OAH_CITIES
    # Real OAH coordinates (no longer synthesized); some sites carry a real
    # ecology/health-risk snapshot.
    assert any(s.get("ecology_latest") for s in sites)
    assert any(s.get("health_risk_latest") for s in sites)
    for s in sites:
        assert -90 <= s["lat"] <= 90
        assert -180 <= s["lng"] <= 180
        assert s["waterbody"] and s["name"]


def test_oah_samples_file_shape():
    data = json.loads((DATA / "oah_samples.json").read_text(encoding="utf-8"))
    assert data["ecology"] and data["health_risk"]
    assert all("site_code" in r and "date" in r for r in data["ecology"])
    assert all("score" in r for r in data["health_risk"])


def test_field_codes_map_to_oah_system():
    data = json.loads((DATA / "oah_field_codes.json").read_text(encoding="utf-8"))
    assert "temporarySystem-oah-eu" in data["code_system"]
    reals = {f["oah_code"] for f in data["fields"] if f["status"] == "real"}
    # The real OAH ecological codes we rely on.
    assert {"foam", "hydrology"} <= reals
