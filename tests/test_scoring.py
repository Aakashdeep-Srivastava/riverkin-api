"""Unit tests for the pure PRD scoring functions (app/scoring.py)."""

from __future__ import annotations

import math

import pytest

from app.scoring import (
    Vote,
    attention_level,
    field_trust,
    initial_reliability,
    need_color,
    need_score,
    observation_trust,
    quality,
    reliability,
    update_reliability,
    value_score,
    verification_state,
    visit_multiplier,
)

# ---- need_score (N_s) ----


def test_need_score_zero_when_fresh_and_covered():
    assert need_score(0.0, visit_share_90d=1.0) == 0.0


def test_need_score_components_sum():
    # Δt/C = 1 (0.4) + (1-0) coverage (0.25) + rain (0.2) + flag (0.15) = 1.0
    n = need_score(
        14.0, cadence_days=14.0, visit_share_90d=0.0, rain_48h_mm=25.0, expert_flag_open=True
    )
    assert n == pytest.approx(1.0)


def test_need_score_staleness_caps_at_cadence():
    # visit_share=1 zeroes the coverage term so staleness is isolated.
    at_cadence = need_score(14.0, cadence_days=14.0, visit_share_90d=1.0)
    beyond = need_score(140.0, cadence_days=14.0, visit_share_90d=1.0)
    assert at_cadence == pytest.approx(0.4)
    assert beyond == pytest.approx(0.4)  # min(1, Δt/C) caps the term


def test_need_score_rain_is_a_threshold():
    below = need_score(0.0, visit_share_90d=1.0, rain_48h_mm=19.9)
    at = need_score(0.0, visit_share_90d=1.0, rain_48h_mm=20.0)
    assert below == pytest.approx(0.0)
    assert at == pytest.approx(0.2)


def test_need_score_coverage_term():
    assert need_score(0.0, visit_share_90d=0.0) == pytest.approx(0.25)
    assert need_score(0.0, visit_share_90d=0.5) == pytest.approx(0.125)


def test_need_score_handles_nonpositive_cadence():
    # Falls back to the default cadence rather than dividing by zero.
    assert 0.0 <= need_score(7.0, cadence_days=0.0) <= 1.0


def test_need_score_clamped_to_unit_interval():
    assert 0.0 <= need_score(1000.0, rain_48h_mm=100.0, expert_flag_open=True) <= 1.0
    assert need_score(-5.0, visit_share_90d=2.0) >= 0.0


# ---- need_color ----


def test_need_color_grey_when_orphan():
    assert need_color(0.9, days_since_check=120.0) == "grey"


def test_need_color_red_only_for_flag():
    assert need_color(0.1, expert_flag_open=True) == "red"


def test_need_color_cyan_and_amber():
    assert need_color(0.2) == "cyan"
    assert need_color(0.3) == "amber"
    assert need_color(0.85) == "amber"


# ---- attention_level ----


@pytest.mark.parametrize(
    ("need", "expect"),
    [(0.7, "urgent"), (0.4, "attention"), (0.2, "monitoring"), (0.05, "ok")],
)
def test_attention_level_bands(need, expect):
    assert attention_level(need) == expect


def test_attention_level_flag_is_urgent():
    assert attention_level(0.05, expert_flag_open=True) == "urgent"


# ---- quality / value / multiplier ----


def test_quality_full_and_empty():
    assert quality(1.0, True, True) == pytest.approx(1.0)
    assert quality(0.0, False, False) == pytest.approx(0.0)
    assert quality(1.0, False, False) == pytest.approx(0.5)


def test_visit_multiplier_rules():
    assert visit_multiplier(0, is_first_in_72h=True) == 1.0
    assert visit_multiplier(1, is_first_in_72h=False) == 0.2
    assert visit_multiplier(3, is_first_in_72h=True) == 0.0


def test_value_score_formula():
    # V = 10*(1+0.5)*1.0*1.0 = 15
    assert value_score(0.5, 1.0, 1.0) == pytest.approx(15.0)
    assert value_score(0.0, 0.0, 1.0) == 0.0


# ---- reliability (Beta) ----


def test_initial_reliability_is_half():
    a, b = initial_reliability()
    assert reliability(a, b) == pytest.approx(0.5)


def test_update_reliability_moves_correctly():
    a, b = initial_reliability()
    for _ in range(8):
        a, b = update_reliability(a, b, correct=True)
    assert reliability(a, b) > 0.8
    a2, b2 = initial_reliability()
    for _ in range(8):
        a2, b2 = update_reliability(a2, b2, correct=False)
    assert reliability(a2, b2) < 0.2


def test_reliability_guards_zero_total():
    assert reliability(0.0, 0.0) == 0.5


# ---- field_trust / observation_trust ----


def test_field_trust_prior_with_no_votes():
    assert field_trust([]) == pytest.approx(0.6)


def test_field_trust_agreeing_reliable_votes_raise_trust():
    votes = [Vote(reliability=0.9, agrees=True) for _ in range(3)]
    assert field_trust(votes) > 0.9


def test_field_trust_disagreeing_votes_lower_trust():
    votes = [Vote(reliability=0.9, agrees=False) for _ in range(3)]
    assert field_trust(votes) < 0.1


def test_field_trust_crewmate_downweighted():
    strong = field_trust([Vote(reliability=0.9, agrees=True, is_crewmate=False)])
    weak = field_trust([Vote(reliability=0.9, agrees=True, is_crewmate=True)])
    assert strong > weak


def test_field_trust_ai_prior_nudges():
    vote = [Vote(reliability=0.7, agrees=True)]
    base = field_trust(vote)
    with_ai = field_trust(vote, ai_agrees=True, ai_confidence=0.9)
    against_ai = field_trust(vote, ai_agrees=False, ai_confidence=0.9)
    assert with_ai > base > against_ai


def test_field_trust_handles_extreme_reliability():
    # Reliability of exactly 0 or 1 must not produce inf/nan.
    t = field_trust([Vote(reliability=1.0, agrees=True), Vote(reliability=0.0, agrees=False)])
    assert 0.0 <= t <= 1.0 and not math.isnan(t)


def test_observation_trust_mean():
    assert observation_trust([]) == 0.0
    assert observation_trust([0.2, 0.8]) == pytest.approx(0.5)


# ---- verification_state ----


def test_verification_state_expert_for_flag_or_split():
    assert verification_state(0.95, 5, pipe_or_sewage_flag=True) == "expert"
    assert verification_state(0.95, 5, any_field_split=True) == "expert"


def test_verification_state_verified():
    assert verification_state(0.85, 3) == "community-verified"
    assert verification_state(0.85, 2) == "pending"  # not enough votes


def test_verification_state_queried_and_pending():
    assert verification_state(0.2, 4) == "queried"
    assert verification_state(0.5, 2) == "pending"
