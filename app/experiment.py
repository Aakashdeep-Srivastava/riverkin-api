"""A/B experiment scaffolding — the AI-assisted vs human-only verification lift.

RiverKin's premise is "AI asks, humans decide". To honestly measure whether the
AI's visual prior actually *helps* verifiers (vs just being shown), we run a
controlled experiment on the verify round:

- **assisted** arm: the verifier sees the AI focus box (``ai_box``).
- **control** arm: the AI box is withheld — a human-only decision.

Assignment is deterministic per (voter, item) via a hash, so a verifier sees a
consistent arm for a given card and the split is stable without storing extra
state. The vote records its arm; the lift metric compares gold-item accuracy and
speed across arms. Until each arm has ``MIN_PER_ARM`` gold votes the result is
reported as insufficient — never presented as a validated measurement (PRD/roadmap:
"needs an A/B control … do not present as measured").
"""

from __future__ import annotations

import hashlib

VERIFY_LIFT_EXPERIMENT = "verify-ai-assist"
ARMS = ("assisted", "control")

# Minimum gold votes per arm before the lift is considered reportable (still not
# a significance test — just a floor against noise from a handful of votes).
MIN_PER_ARM = 30


def assign_arm(voter_id: str, item_id: int) -> str:
    """Deterministically assign a (voter, item) pair to an experiment arm."""
    digest = hashlib.sha256(f"{voter_id}:{item_id}".encode()).digest()
    return ARMS[digest[0] % 2]
