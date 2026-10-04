"""Correlate the citizen's field answers with the vision model's per-field read.

PURE functions (no I/O). The output is a WEAK per-field prior and a list of
discrepancies — never a verdict. It feeds ``scoring.field_trust`` (the AI term)
and can escalate an observation to human expert review. "AI asks, humans decide."

Both the citizen answer and the model value are mapped to a small *concern
ordinal* (0 good · 1 some · 2 clear concern); adjacent values are treated as
agreement, only a two-step gap is a contradiction.
"""

from __future__ import annotations

from dataclasses import dataclass

CONSIDER_CONFIDENCE = 0.4  # ignore model reads below this
FLAG_CONFIDENCE = 0.7  # a disagreement this confident is a discrepancy
POLLUTION_FIELDS = {"q-water", "q-foam", "q-litter", "q-pipe"}

# Citizen answer value → concern ordinal, per front-end question key.
_CITIZEN_CONCERN: dict[str, dict[str, int]] = {
    "q-water": {"clear": 0, "slightly_cloudy": 1, "cloudy": 2, "very_turbid": 2},
    "q-foam": {"none": 0, "patches": 1, "lots": 2},
    "q-litter": {"none": 0, "some": 1, "a_lot": 2},
    "q-pipe": {"no": 0, "cant_tell": -1, "yes": 2},
    "q-flow": {"low": 1, "normal": 0, "high": 1},
}

# Model field value → concern ordinal, per model field key.
_MODEL_CONCERN: dict[str, dict[str, int]] = {
    "water_appearance": {"clear": 0, "slightly_turbid": 1, "turbid": 2},
    "foam": {"none": 0, "some": 1, "lots": 2},
    "litter": {"none": 0, "some": 1, "lots": 2},
    "pipe_outfall": {"none": 0, "visible": 2},
    "flow": {"low": 1, "normal": 0, "high": 1},
}

# Front-end question key → model field key.
_KEY_TO_MODEL_FIELD = {
    "q-water": "water_appearance",
    "q-foam": "foam",
    "q-litter": "litter",
    "q-pipe": "pipe_outfall",
    "q-flow": "flow",
}


@dataclass(frozen=True)
class FieldCorrelation:
    key: str  # front-end question key (q-water, ...)
    citizen: str
    model_value: str
    confidence: float
    agrees: bool | None  # None = model abstained / not comparable
    is_discrepancy: bool


def correlate_field(
    key: str, citizen_value: str, model_entry: dict | None
) -> FieldCorrelation | None:
    """Correlate one field. Returns None if there is nothing to compare."""
    model_field = _KEY_TO_MODEL_FIELD.get(key)
    if model_field is None or not model_entry:
        return None
    conf = float(model_entry.get("confidence") or 0.0)
    model_value = str(model_entry.get("value") or "")
    cc = _CITIZEN_CONCERN.get(key, {}).get(str(citizen_value))
    mc = _MODEL_CONCERN.get(model_field, {}).get(model_value)
    if cc is None or cc < 0 or mc is None or conf < CONSIDER_CONFIDENCE:
        # Model (or citizen) abstains / not comparable → neutral, no AI term.
        return FieldCorrelation(key, str(citizen_value), model_value, conf, None, False)
    agrees = abs(cc - mc) <= 1
    discrepancy = (not agrees) and conf >= FLAG_CONFIDENCE
    return FieldCorrelation(key, str(citizen_value), model_value, conf, agrees, discrepancy)


@dataclass(frozen=True)
class Correlation:
    per_field: list[FieldCorrelation]
    discrepancies: list[FieldCorrelation]
    escalate: bool  # a confident, pollution-relevant contradiction → expert review


def correlate(answers: dict, model_fields: dict) -> Correlation:
    """Correlate all answered fields with the model's reads (FIELD_SPECS order)."""
    from app.ai.questions import FIELD_SPECS  # local import avoids a cycle

    per_field: list[FieldCorrelation] = []
    for spec in FIELD_SPECS:
        key = spec["key"]
        if answers.get(key) is None:
            continue
        model_field = _KEY_TO_MODEL_FIELD.get(key)
        entry = model_fields.get(model_field) if model_field else None
        fc = correlate_field(key, str(answers[key]), entry)
        if fc is not None:
            per_field.append(fc)
    discrepancies = [f for f in per_field if f.is_discrepancy]
    escalate = any(f.key in POLLUTION_FIELDS for f in discrepancies)
    return Correlation(per_field=per_field, discrepancies=discrepancies, escalate=escalate)
