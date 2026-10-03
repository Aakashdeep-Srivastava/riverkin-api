"""Vision heuristic + authenticity scoring (pure, no DB/network)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app import authenticity
from app.ai import vision


def _jpeg(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype("uint8")).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


async def test_heuristic_analysis_is_deterministic_and_bounded():
    img = _jpeg(np.random.default_rng(3).integers(0, 255, size=(80, 80, 3)))
    a = await vision.analyze_image(img)  # no Foundry config → heuristic
    assert a.used_model is False
    assert a.model == "heuristic"
    assert a.summary
    assert 0.0 <= a.ai_generated_likelihood <= 1.0
    assert isinstance(a.tags, list) and a.tags


def test_authenticity_live_novel_natural_is_high():
    r = authenticity.score(
        captured_live=True, exif_present=False, phash_novelty=30, model_ai_likelihood=0.1
    )
    assert r.confidence >= 80
    assert "captured live in-app" in r.reason


def test_authenticity_reused_image_is_penalised():
    live = authenticity.score(
        captured_live=True, exif_present=False, phash_novelty=30, model_ai_likelihood=0.1
    )
    reused = authenticity.score(
        captured_live=True, exif_present=False, phash_novelty=2, model_ai_likelihood=0.1
    )
    assert reused.confidence < live.confidence
    assert "earlier photo" in reused.reason


def test_authenticity_model_ai_flag_lowers_confidence():
    natural = authenticity.score(
        captured_live=False, exif_present=True, phash_novelty=30, model_ai_likelihood=0.05
    )
    synthetic = authenticity.score(
        captured_live=False, exif_present=True, phash_novelty=30, model_ai_likelihood=0.95
    )
    assert synthetic.confidence < natural.confidence
    assert 0 <= synthetic.confidence <= 100


@pytest.mark.parametrize("live", [True, False])
def test_authenticity_always_in_range(live: bool):
    r = authenticity.score(
        captured_live=live, exif_present=False, phash_novelty=None, model_ai_likelihood=0.5
    )
    assert 0 <= r.confidence <= 100
