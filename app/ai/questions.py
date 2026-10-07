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


# Canonical verifiable fields, keyed by the front-end question id, mapped to the
# real OAH code system (see data/oah_field_codes.json).
FIELD_SPECS: list[dict[str, str]] = [
    {"key": "q-water", "field_code": "water", "label": "water appearance"},
    {"key": "q-litter", "field_code": "litter", "label": "litter / debris"},
    {"key": "q-foam", "field_code": "foam", "label": "surface foam"},
    {"key": "q-flow", "field_code": "hydrology", "label": "flow"},
    {"key": "q-pipe", "field_code": "pipe_outfall", "label": "pipe / outfall"},
]


def build_verify_items(answers: dict[str, Any]) -> list[dict[str, Any]]:
    """Draft one verify item per answered field (the "AI asks" step).

    Deterministic when ``VLM_PROVIDER == "none"`` (CI + offline demo). The model
    only drafts the neutral question + a weak prior; a human decides by voting.
    Every fifth item is a hidden gold-standard item (PRD: 1 in 5).
    """
    items: list[dict[str, Any]] = []
    gold_index = 0
    for spec in FIELD_SPECS:
        value = answers.get(spec["key"])
        if value is None:
            continue
        pretty = str(value).replace("_", " ")
        is_gold = gold_index % 5 == 0
        items.append(
            {
                "field_code": spec["field_code"],
                "question": (
                    f"The observer recorded {spec['label']} as “{pretty}”. "
                    "Does the photo support that?"
                ),
                "ai_box": f"RiverKin AI drafted this check for {spec['label']}; humans decide.",
                "ai_agrees": True,
                "ai_confidence": 0.5,
                "is_gold": is_gold,
                "gold_answer": "yes" if is_gold else None,
            }
        )
        gold_index += 1
    return items
