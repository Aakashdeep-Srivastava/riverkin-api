"""Pure validation of the bundled OAH data files (no DB)."""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

OAH_CITIES = {"Coimbra", "Toulouse", "Benevento", "Ghent", "Oslo"}


def test_oah_sites_file_shape():
    data = json.loads((DATA / "oah_sites.json").read_text(encoding="utf-8"))
    assert data["count"] == 106
    sites = data["sites"]
    assert len(sites) == 106
    codes = {s["oah_code"] for s in sites}
    assert len(codes) == 106  # unique codes
    cities = {s["city"] for s in sites}
    assert cities == OAH_CITIES
    for s in sites:
        assert -90 <= s["lat"] <= 90
        assert -180 <= s["lng"] <= 180
        assert s["waterbody"] and s["name"]
        assert s["simulated_coordinates"] is True


def test_field_codes_map_to_oah_system():
    data = json.loads((DATA / "oah_field_codes.json").read_text(encoding="utf-8"))
    assert "temporarySystem-oah-eu" in data["code_system"]
    reals = {f["oah_code"] for f in data["fields"] if f["status"] == "real"}
    # The real OAH ecological codes we rely on.
    assert {"foam", "hydrology"} <= reals
