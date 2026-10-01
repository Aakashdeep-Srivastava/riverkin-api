"""Pure scoring functions — no I/O, fully unit-testable.

These are deterministic placeholders. The exact formulas (weights, decay,
clamping, normalisation) come from the PRD Algorithms section.

Every function returns a float clamped to [0.0, 1.0] so downstream code and the
API contract can rely on a stable range while the real math is pending.
"""

from __future__ import annotations

from collections.abc import Sequence


def _clamp01(x: float) -> float:
    """Clamp a value into the closed interval [0.0, 1.0]."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def need_score(
    rain_mm: float,
    days_since_last_observation: float,
    *,
    rain_weight: float = 0.6,
    staleness_weight: float = 0.4,
) -> float:
    """Site need score N_s.

    Higher when recent rainfall is high (runoff/pollution risk) and when the
    site has not been observed in a while.

    TODO(PRD): exact formula — real rain normalisation window, staleness decay
    curve, and any catchment/risk multipliers from the Algorithms section.
    """
    # Placeholder normalisation: saturate rain at 50 mm, staleness at 30 days.
    rain_component = _clamp01(rain_mm / 50.0)
    staleness_component = _clamp01(days_since_last_observation / 30.0)
    return _clamp01(rain_weight * rain_component + staleness_weight * staleness_component)


def value_score(
    need: float,
    novelty: float,
    *,
    need_weight: float = 0.7,
    novelty_weight: float = 0.3,
) -> float:
    """Reward value of an observation.

    Rewards follow this value formula (CLAUDE.md: no points-per-submission).

    TODO(PRD): exact formula — the PRD value formula drives real rewards.
    """
    return _clamp01(need_weight * _clamp01(need) + novelty_weight * _clamp01(novelty))


def reliability_score(
    photo_quality: float,
    metadata_completeness: float,
    *,
    photo_weight: float = 0.5,
    metadata_weight: float = 0.5,
) -> float:
    """Per-observation reliability prior (before human verification).

    TODO(PRD): exact formula — real inputs (blur score, EXIF consistency,
    geofence pass, pHash dedup) and weights from the Algorithms section.
    """
    return _clamp01(
        photo_weight * _clamp01(photo_quality)
        + metadata_weight * _clamp01(metadata_completeness)
    )


def trust_score(
    votes_correct: int,
    votes_total: int,
    *,
    prior: float = 0.5,
    prior_strength: float = 2.0,
) -> float:
    """Observer/verifier trust from verify-round voting history.

    Uses a smoothed (Laplace-style) agreement ratio so a brand-new user starts
    at ``prior`` instead of 0 or 1.

    TODO(PRD): exact formula — gold-item weighting, time decay, and abuse
    guards from the Algorithms / verification sections.
    """
    if votes_total < 0 or votes_correct < 0 or votes_correct > votes_total:
        raise ValueError("votes_correct must be in [0, votes_total] and non-negative")
    numerator = votes_correct + prior * prior_strength
    denominator = votes_total + prior_strength
    return _clamp01(numerator / denominator)


def aggregate_need(site_needs: Sequence[float]) -> float:
    """Convenience aggregate (e.g. catchment-level need = max of member sites).

    TODO(PRD): confirm whether catchment need is max, mean, or weighted.
    """
    if not site_needs:
        return 0.0
    return _clamp01(max(site_needs))
