"""Unit tests for the pure scoring functions (app/scoring.py)."""

from __future__ import annotations

import pytest

from app.scoring import (
    aggregate_need,
    need_score,
    reliability_score,
    trust_score,
    value_score,
)


def test_all_scores_stay_in_unit_interval():
    assert 0.0 <= need_score(1000.0, 1000.0) <= 1.0
    assert 0.0 <= value_score(5.0, -5.0) <= 1.0
    assert 0.0 <= reliability_score(2.0, -1.0) <= 1.0
    assert 0.0 <= trust_score(10, 10) <= 1.0


def test_need_score_zero_and_saturation():
    assert need_score(0.0, 0.0) == 0.0
    # Fully saturated rain + staleness -> 1.0.
    assert need_score(50.0, 30.0) == pytest.approx(1.0)


def test_need_score_monotonic_in_rain():
    low = need_score(5.0, 0.0)
    high = need_score(25.0, 0.0)
    assert high > low


def test_value_score_weights():
    # need=1, novelty=0 -> need_weight (0.7).
    assert value_score(1.0, 0.0) == pytest.approx(0.7)
    assert value_score(0.0, 1.0) == pytest.approx(0.3)


def test_reliability_score_midpoint():
    assert reliability_score(1.0, 0.0) == pytest.approx(0.5)
    assert reliability_score(1.0, 1.0) == pytest.approx(1.0)


def test_trust_score_prior_for_new_user():
    # No votes -> falls back to the smoothed prior (0.5).
    assert trust_score(0, 0) == pytest.approx(0.5)


def test_trust_score_moves_toward_agreement():
    many_correct = trust_score(100, 100)
    many_wrong = trust_score(0, 100)
    assert many_correct > 0.9
    assert many_wrong < 0.1


def test_trust_score_rejects_bad_counts():
    with pytest.raises(ValueError):
        trust_score(5, 3)
    with pytest.raises(ValueError):
        trust_score(-1, 3)


def test_aggregate_need():
    assert aggregate_need([]) == 0.0
    assert aggregate_need([0.1, 0.9, 0.3]) == pytest.approx(0.9)
