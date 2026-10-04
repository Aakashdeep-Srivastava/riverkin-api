"""Unit tests for app/vision_fields.py — image↔answer correlation (pure)."""

from __future__ import annotations

from app import vision_fields as vf


def _entry(value: str, confidence: float) -> dict:
    return {"value": value, "confidence": confidence}


def test_agreement_sets_positive_prior():
    fc = vf.correlate_field("q-foam", "none", _entry("none", 0.9))
    assert fc is not None
    assert fc.agrees is True
    assert fc.is_discrepancy is False
    assert fc.confidence == 0.9


def test_adjacent_values_still_agree():
    # citizen "patches" (1) vs model "none" (0) → within tolerance.
    fc = vf.correlate_field("q-foam", "patches", _entry("none", 0.8))
    assert fc.agrees is True
    assert fc.is_discrepancy is False


def test_confident_contradiction_is_a_discrepancy():
    # citizen "clear" (0) vs model "turbid" (2), high confidence → contradiction.
    fc = vf.correlate_field("q-water", "clear", _entry("turbid", 0.85))
    assert fc.agrees is False
    assert fc.is_discrepancy is True


def test_low_confidence_model_abstains():
    fc = vf.correlate_field("q-litter", "none", _entry("lots", 0.2))
    assert fc.agrees is None  # below consider threshold → neutral, no AI term
    assert fc.is_discrepancy is False


def test_cant_tell_citizen_is_neutral():
    fc = vf.correlate_field("q-pipe", "cant_tell", _entry("visible", 0.9))
    assert fc.agrees is None


def test_correlate_escalates_on_pollution_contradiction():
    answers = {"q-water": "clear", "q-litter": "none", "q-flow": "normal"}
    model_fields = {
        "water_appearance": _entry("turbid", 0.9),  # confident contradiction
        "litter": _entry("none", 0.8),  # agrees
        "flow": _entry("normal", 0.1),  # abstains (low conf)
    }
    corr = vf.correlate(answers, model_fields)
    assert corr.escalate is True
    assert any(d.key == "q-water" for d in corr.discrepancies)
    # one field per answered key that maps to a model field
    assert {f.key for f in corr.per_field} == {"q-water", "q-litter", "q-flow"}


def test_correlate_no_escalation_when_agreeing():
    answers = {"q-water": "clear", "q-foam": "none"}
    model_fields = {"water_appearance": _entry("clear", 0.9), "foam": _entry("none", 0.9)}
    corr = vf.correlate(answers, model_fields)
    assert corr.escalate is False
    assert corr.discrepancies == []


def test_aggregate_photo_fields_consensus_boost():
    """Collective read: agreeing photos boost confidence; strongest value wins."""
    photos = [
        {"fields": {"foam": {"value": "lots", "confidence": 0.6}}},
        {"fields": {"foam": {"value": "lots", "confidence": 0.5}}},
        {"fields": {"litter": {"value": "none", "confidence": 0.9}}},
    ]
    agg = vf.aggregate_photo_fields(photos)
    assert agg["foam"]["value"] == "lots"
    assert agg["foam"]["photos"] == 2
    assert agg["foam"]["confidence"] > 0.6  # consensus boost over the single max
    assert agg["litter"]["value"] == "none" and agg["litter"]["photos"] == 1


def test_aggregate_prefers_value_with_most_evidence():
    photos = [
        {"fields": {"water_appearance": {"value": "clear", "confidence": 0.4}}},
        {"fields": {"water_appearance": {"value": "clear", "confidence": 0.4}}},
        {"fields": {"water_appearance": {"value": "turbid", "confidence": 0.7}}},
    ]
    agg = vf.aggregate_photo_fields(photos)
    # Two photos at 0.4 (sum 0.8) outweigh one at 0.7 → "clear".
    assert agg["water_appearance"]["value"] == "clear"
