"""Pure scoring functions — no I/O, fully unit-testable.

These implement the RiverKin Algorithms section of the PRD exactly. Every
function is deterministic and side-effect free so it can be unit tested with
fixed fixtures and shown in the README.

Formulas
--------
Site need (recomputed nightly and after every check or rain pull), where
``Δt`` is days since the last verified check, ``C`` the cadence (14 days),
``v`` the share of ideal visits in 90 days, ``R = 1`` if rain ≥ 20 mm in 48 h,
``D = 1`` if an expert flag is open::

    N_s = 0.4·min(1, Δt/C) + 0.25·(1 − v) + 0.2·R + 0.15·D

Map colour: N < 0.3 cyan; 0.3–0.6 amber; D = 1 red; no check in 90 days grey.

Observation value (River Value), with ``Q = 0.5·completeness + 0.3·photo_ok +
0.2·geo_ok`` and ``M = 1`` for the first check per site per crew in 72 h, 0.2
after, 0 beyond 3 checks a day::

    V = 10·(1 + N_s)·Q·M

Verifier reliability: Beta posterior on gold items, starting α = β = 2; +1 α if
correct, +1 β if wrong::

    r_u = α_u / (α_u + β_u)

Per-field trust (log-odds pooling), ``a_u = +1`` if the vote agrees with the
submitter else −1; ``w_u = 0.5`` for crew-mates else 1; the AI term has
λ = 0.5; ``p0 = 0.6``::

    L_f = logit(p0) + Σ_u w_u·a_u·logit(r_u) + λ·a_AI·c_AI,   T_f = σ(L_f)

Observation trust ``T`` is the mean of ``T_f``. "Can't tell" votes add no
evidence (the caller omits them).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# ---- Constants (PRD) ----
CADENCE_DAYS_DEFAULT = 14.0
RAIN_THRESHOLD_MM = 20.0
ORPHAN_DAYS = 90.0
PRIOR_P0 = 0.6
AI_LAMBDA = 0.5
BETA_PRIOR = 2.0
VERIFIED_TRUST = 0.8
VERIFIED_MIN_VOTES = 3
QUERIED_TRUST = 0.3
MAX_CHECKS_PER_DAY = 3


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp ``x`` into ``[lo, hi]``."""
    return lo if x < lo else hi if x > hi else x


def _logit(p: float) -> float:
    """Log-odds of ``p`` (clamped off 0/1 to stay finite)."""
    p = _clamp(p, 1e-6, 1.0 - 1e-6)
    return math.log(p / (1.0 - p))


def _sigmoid(x: float) -> float:
    """Logistic function σ(x)."""
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


# ============================================================
# Site need  N_s
# ============================================================
def need_score(
    days_since_check: float,
    *,
    cadence_days: float = CADENCE_DAYS_DEFAULT,
    visit_share_90d: float = 0.0,
    rain_48h_mm: float = 0.0,
    expert_flag_open: bool = False,
) -> float:
    """Site need N_s ∈ [0, 1]. Higher = needs a fresh verified check sooner.

    Rewards fresh, verified coverage — never volume.
    """
    c = cadence_days if cadence_days > 0 else CADENCE_DAYS_DEFAULT
    staleness = 0.4 * min(1.0, max(0.0, days_since_check) / c)
    coverage = 0.25 * (1.0 - _clamp(visit_share_90d))
    rain = 0.2 * (1.0 if rain_48h_mm >= RAIN_THRESHOLD_MM else 0.0)
    flag = 0.15 * (1.0 if expert_flag_open else 0.0)
    return _clamp(staleness + coverage + rain + flag)


def need_color(
    need: float,
    *,
    expert_flag_open: bool = False,
    days_since_check: float = 0.0,
) -> str:
    """Map a need score to the PRD pulse colour.

    grey (unseen ≥ 90 d) · red (open expert flag) · cyan (< 0.3) · amber (≥ 0.3).
    Red is reserved for unresolved pollution flags, never a user failure.
    """
    if days_since_check >= ORPHAN_DAYS:
        return "grey"
    if expert_flag_open:
        return "red"
    if need < 0.3:
        return "cyan"
    return "amber"


def attention_level(
    need: float,
    *,
    days_since_check: float = 0.0,
    expert_flag_open: bool = False,
) -> str:
    """Map a need score to the four front-end attention levels.

    urgent · attention · monitoring · ok (status is colour + icon + label in UI).
    """
    if expert_flag_open or need >= 0.6:
        return "urgent"
    if need >= 0.35:
        return "attention"
    if need >= 0.15:
        return "monitoring"
    return "ok"


# ============================================================
# Observation value  V
# ============================================================
def quality(completeness: float, photo_ok: bool, geo_ok: bool) -> float:
    """Observation quality Q ∈ [0, 1]."""
    photo = 1.0 if photo_ok else 0.0
    geo = 1.0 if geo_ok else 0.0
    return _clamp(0.5 * _clamp(completeness) + 0.3 * photo + 0.2 * geo)


def visit_multiplier(prior_checks_today: int, *, is_first_in_72h: bool) -> float:
    """Repeat-visit multiplier M (anti-farming): 1 first per 72 h, 0.2 after,
    0 beyond 3 checks a day."""
    if prior_checks_today >= MAX_CHECKS_PER_DAY:
        return 0.0
    return 1.0 if is_first_in_72h else 0.2


def value_score(need: float, quality_q: float, multiplier: float) -> float:
    """River Value V = 10·(1 + N_s)·Q·M (not bounded to 1)."""
    return 10.0 * (1.0 + need) * _clamp(quality_q) * max(0.0, multiplier)


# ============================================================
# Verifier reliability  r_u  (Beta posterior over gold items)
# ============================================================
def initial_reliability() -> tuple[float, float]:
    """Starting Beta parameters (α = β = 2)."""
    return (BETA_PRIOR, BETA_PRIOR)


def update_reliability(alpha: float, beta: float, *, correct: bool) -> tuple[float, float]:
    """Bayesian update after one gold item."""
    return (alpha + 1.0, beta) if correct else (alpha, beta + 1.0)


def reliability(alpha: float, beta: float) -> float:
    """Posterior mean reliability r_u = α / (α + β)."""
    total = alpha + beta
    if total <= 0:
        return 0.5
    return alpha / total


# ============================================================
# Per-field + observation trust  (log-odds pooling)
# ============================================================
@dataclass(frozen=True)
class Vote:
    """A single verification vote. "Can't tell" votes are simply omitted."""

    reliability: float
    agrees: bool
    is_crewmate: bool = False


def field_trust(
    votes: Sequence[Vote],
    *,
    ai_agrees: bool | None = None,
    ai_confidence: float = 0.0,
    prior: float = PRIOR_P0,
) -> float:
    """Per-field trust T_f = σ(L_f) via log-odds pooling.

    ``ai_agrees`` is the weak AI prior (None if no AI signal); it never fills a
    field, only nudges the odds.
    """
    log_odds = _logit(prior)
    for v in votes:
        w = 0.5 if v.is_crewmate else 1.0
        a = 1.0 if v.agrees else -1.0
        log_odds += w * a * _logit(v.reliability)
    if ai_agrees is not None:
        a_ai = 1.0 if ai_agrees else -1.0
        log_odds += AI_LAMBDA * a_ai * _clamp(ai_confidence)
    return _sigmoid(log_odds)


def observation_trust(field_trusts: Sequence[float]) -> float:
    """Observation trust T = mean of per-field trusts (0 when none)."""
    if not field_trusts:
        return 0.0
    return sum(field_trusts) / len(field_trusts)


def verification_state(
    trust: float,
    n_votes: int,
    *,
    any_field_split: bool = False,
    pipe_or_sewage_flag: bool = False,
) -> str:
    """Observation lifecycle state from trust + vote count.

    expert (split field or pipe/sewage flag) · community-verified (T ≥ 0.8 and
    ≥ 3 votes) · queried (T ≤ 0.3) · pending otherwise.
    """
    if pipe_or_sewage_flag or any_field_split:
        return "expert"
    if trust >= VERIFIED_TRUST and n_votes >= VERIFIED_MIN_VOTES:
        return "community-verified"
    if trust <= QUERIED_TRUST:
        return "queried"
    return "pending"
