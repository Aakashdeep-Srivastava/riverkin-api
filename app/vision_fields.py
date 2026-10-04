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


def model_field_for(key: str) -> str | None:
    """Map a front-end question key (q-water) to the model field (water_appearance)."""
    return _KEY_TO_MODEL_FIELD.get(key)


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


def aggregate_photo_fields(photos: list[dict]) -> dict[str, dict]:
    """Collapse the per-field reads of 1–5 photos into one collective read.

    For each field, pick the value with the strongest evidence across photos:
    sum confidence per candidate value, choose the top value, and BOOST its
    confidence when ≥2 photos agree (consensus) — capped at 0.98. This is the
    "collective algorithm": more images that agree → a stronger prior; a lone
    low-confidence guess stays weak. Pure, order-independent.
    """
    # field -> value -> [(confidence, question)]
    tally: dict[str, dict[str, list[tuple[float, str | None]]]] = {}
    for ph in photos:
        for key, entry in (ph.get("fields") or {}).items():
            if not isinstance(entry, dict):
                continue
            val = str(entry.get("value") or "")
            conf = float(entry.get("confidence") or 0.0)
            if not val or conf <= 0:
                continue
            q = entry.get("question") if isinstance(entry.get("question"), str) else None
            tally.setdefault(key, {}).setdefault(val, []).append((conf, q))

    collective: dict[str, dict] = {}
    for key, values in tally.items():
        # Best value = highest total confidence mass across photos.
        best_val, entries = max(values.items(), key=lambda kv: sum(c for c, _ in kv[1]))
        confs = [c for c, _ in entries]
        agree = len(confs)
        base = max(confs)
        # Consensus boost: each additional agreeing photo adds 10%, capped.
        boosted = min(0.98, base + 0.10 * (agree - 1))
        # The GPT-written question from the most confident photo for that value.
        question = max(entries, key=lambda cq: cq[0])[1]
        out: dict = {"value": best_val, "confidence": round(boosted, 3), "photos": agree}
        if question:
            out["question"] = question
        collective[key] = out
    return collective


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
