"""Labelled evaluation harness for the vision model (accuracy scaffolding).

RiverKin's photo check uses a vision model to judge *relevance* (is this really a
river/stream photo?) and *AI-generated likelihood*. To report model accuracy
honestly we need a labelled ecological eval set — this module is the scoring
machinery; ``scripts/eval_vision.py`` is the runner.

Populate ``data/eval/manifest.json`` with real, human-labelled examples (see
``data/eval/README.md``). Until then the runner reports zero examples rather than
inventing an accuracy number (PRD/roadmap: model accuracy "needs a labelled
ecological evaluation set"; do not present as measured).

Only the scoring/aggregation is here (pure, unit-tested); image I/O and the model
call live in the runner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class EvalCase:
    image: str
    is_relevant: bool
    is_ai_generated: bool | None = None
    expected_tags: list[str] | None = None


@dataclass
class Prediction:
    relevance: float
    ai_generated_likelihood: float
    tags: list[str]


def load_manifest(path: Path) -> list[EvalCase]:
    """Parse the labelled manifest. Missing/empty file → no cases (not an error)."""
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases", raw) if isinstance(raw, dict) else raw
    return [
        EvalCase(
            image=c["image"],
            is_relevant=bool(c["is_relevant"]),
            is_ai_generated=c.get("is_ai_generated"),
            expected_tags=c.get("expected_tags"),
        )
        for c in cases
    ]


def relevance_correct(pred: float, expected: bool, threshold: float = 0.5) -> bool:
    return (pred >= threshold) == expected


def ai_generated_correct(pred: float, expected: bool, threshold: float = 0.5) -> bool:
    return (pred >= threshold) == expected


def tag_recall(pred_tags: list[str], expected_tags: list[str] | None) -> float | None:
    """Fraction of expected tags matched (loose substring, case-insensitive)."""
    if not expected_tags:
        return None
    preds = [t.lower() for t in pred_tags]
    hits = sum(1 for e in expected_tags if any(e.lower() in p or p in e.lower() for p in preds))
    return round(hits / len(expected_tags), 3)


def aggregate(cases: list[EvalCase], preds: list[Prediction]) -> dict:
    """Aggregate per-dimension accuracy with sample sizes. Honest: null when n=0."""
    rel_n = rel_ok = 0
    ai_n = ai_ok = 0
    recalls: list[float] = []
    for case, pred in zip(cases, preds, strict=True):
        rel_n += 1
        rel_ok += int(relevance_correct(pred.relevance, case.is_relevant))
        if case.is_ai_generated is not None:
            ai_n += 1
            ai_ok += int(ai_generated_correct(pred.ai_generated_likelihood, case.is_ai_generated))
        r = tag_recall(pred.tags, case.expected_tags)
        if r is not None:
            recalls.append(r)
    return {
        "n": rel_n,
        "relevance_accuracy_pct": round(100 * rel_ok / rel_n) if rel_n else None,
        "ai_detection_n": ai_n,
        "ai_detection_accuracy_pct": round(100 * ai_ok / ai_n) if ai_n else None,
        "tag_recall_mean": round(sum(recalls) / len(recalls), 3) if recalls else None,
        "note": "Experimental — requires a real labelled ecological set; not validated.",
    }
