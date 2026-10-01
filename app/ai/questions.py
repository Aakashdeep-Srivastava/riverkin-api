"""VLM-backed verify-question generation with a deterministic fallback.

Hard rule (CLAUDE.md): the model only writes verify *questions* and a weak
prior. It never fills a field; humans decide.

When ``VLM_PROVIDER == "none"`` (the default, and what CI uses) this returns a
fixed, deterministic list so the rest of the system is fully testable offline.
"""

from __future__ import annotations

from typing import Any

from app.config import settings

# Deterministic offline questions. Kept generic until the PRD defines the real
# per-parameter question bank.
_FALLBACK_QUESTIONS: list[str] = [
    "Is the water body clearly visible in the photo?",
    "Does the photo appear to be taken at the claimed site?",
    "Are there visible signs of pollution (foam, debris, discolouration)?",
]


def generate_questions(observation_context: dict[str, Any]) -> list[str]:
    """Return verify questions for an observation.

    Args:
        observation_context: placeholder for photo features / measured fields.
            TODO(PRD): define the real context schema the VLM consumes.

    Returns:
        A list of human-answerable yes/no-ish verification questions.
    """
    if settings.VLM_PROVIDER == "none":
        return list(_FALLBACK_QUESTIONS)

    # TODO(PRD): call the configured provider (moondream | hosted) using
    # settings.VLM_API_KEY, pass the processed photo + context, and return the
    # generated questions. On any provider error, fall back to the list below.
    return list(_FALLBACK_QUESTIONS)


def weak_prior(observation_context: dict[str, Any]) -> float:
    """Return a weak model prior in [0, 1] that a claim is plausible.

    TODO(PRD): real prior from the VLM. Never used to fill a field — only to
    order/seed human verification.
    """
    return 0.5
