"""Unit tests for app/oah.py — classification of real OAH baseline values."""

from __future__ import annotations

from app import oah


def test_ecology_status_is_worst_element():
    """WFD 'one out, all out': status is the worst available quality class."""
    eco = {
        "macroinvertebratesQuality": "Good",
        "macroinvertebratesRichness": 18,
        "diatomsQuality": "Moderate",
        "fishQuality": "Bad",
        "fishRichness": 2,
        "nitrate": 0.5,
        "date": "2024-04-05T00:00:00Z",
    }
    out = oah.ecology_status(eco)
    assert out["status"] == "Bad"
    assert out["worst_element"] == "fish"
    assert out["color"] == "#E5484D"
    assert out["nitrate"] == 0.5
    assert len(out["elements"]) == 3


def test_ecology_status_ignores_empty_quality():
    """Empty-string quality classes (present in OAH data) count as absent."""
    eco = {"macroinvertebratesQuality": "", "macroinvertebratesRichness": 15, "date": "x"}
    out = oah.ecology_status(eco)
    assert out is not None
    assert out["status"] is None  # no usable class → no roll-up
    assert out["elements"][0]["richness"] == 15


def test_ecology_status_none_when_empty():
    assert oah.ecology_status(None) is None
    assert oah.ecology_status({}) is None


def test_health_risk_bands():
    assert oah.health_risk_band({"score": 0.1})["band"] == "low"
    assert oah.health_risk_band({"score": 0.5})["band"] == "moderate"
    assert oah.health_risk_band({"score": 0.8})["band"] == "high"
    assert oah.health_risk_band(None) is None
    assert oah.health_risk_band({"pathogen": 0.2}) is None  # no score key
