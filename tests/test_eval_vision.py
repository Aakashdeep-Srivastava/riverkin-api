"""Unit tests for the vision eval scoring (pure — no model, no DB)."""

from __future__ import annotations

from pathlib import Path

from app.eval_vision import (
    EvalCase,
    Prediction,
    aggregate,
    ai_generated_correct,
    load_manifest,
    relevance_correct,
    tag_recall,
)


def test_load_manifest_missing_is_empty(tmp_path: Path):
    assert load_manifest(tmp_path / "nope.json") == []


def test_relevance_and_ai_thresholds():
    assert relevance_correct(0.8, True)
    assert not relevance_correct(0.2, True)
    assert relevance_correct(0.2, False)
    assert ai_generated_correct(0.9, True)
    assert not ai_generated_correct(0.9, False)


def test_tag_recall():
    assert tag_recall(["river", "green-algae"], ["river", "algae"]) == 1.0  # loose substring
    assert tag_recall(["sky"], ["river"]) == 0.0
    assert tag_recall(["x"], None) is None


def test_aggregate_honest_nulls_and_accuracy():
    cases = [
        EvalCase(image="a.jpg", is_relevant=True, is_ai_generated=False, expected_tags=["river"]),
        EvalCase(image="b.jpg", is_relevant=False),  # off-topic, no ai/tag labels
    ]
    preds = [
        Prediction(relevance=0.9, ai_generated_likelihood=0.1, tags=["river", "bank"]),
        Prediction(relevance=0.2, ai_generated_likelihood=0.5, tags=["room"]),
    ]
    out = aggregate(cases, preds)
    assert out["n"] == 2
    assert out["relevance_accuracy_pct"] == 100  # both relevance calls correct
    assert out["ai_detection_n"] == 1 and out["ai_detection_accuracy_pct"] == 100
    assert out["tag_recall_mean"] == 1.0
    assert "Experimental" in out["note"]


def test_aggregate_empty_is_null():
    out = aggregate([], [])
    assert out["n"] == 0
    assert out["relevance_accuracy_pct"] is None
    assert out["ai_detection_accuracy_pct"] is None
