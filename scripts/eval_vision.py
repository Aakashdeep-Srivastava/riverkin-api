"""Run the vision model against the labelled eval set and report accuracy.

    python scripts/eval_vision.py

Reads data/eval/manifest.json, runs app/ai/vision.analyze_image over each image
in data/eval/images/, and prints per-dimension accuracy with sample sizes. Uses
whatever vision provider is configured (real Foundry model if FOUNDRY_* is set,
else the deterministic heuristic — the report states which). With no labelled
cases it reports zero rather than inventing a number. See data/eval/README.md.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ai.vision import analyze_image  # noqa: E402
from app.eval_vision import Prediction, aggregate, load_manifest  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "eval"
MANIFEST = EVAL_DIR / "manifest.json"
IMAGES = EVAL_DIR / "images"


async def main() -> None:
    cases = load_manifest(MANIFEST)
    if not cases:
        print(
            "No labelled examples in data/eval/manifest.json.\n"
            "Add real images to data/eval/images/ and label them (see "
            "data/eval/README.md) to measure vision accuracy."
        )
        return

    preds: list[Prediction] = []
    used_model = None
    for case in cases:
        raw = (IMAGES / case.image).read_bytes()
        a = await analyze_image(raw)
        used_model = a.used_model if used_model is None else used_model
        preds.append(
            Prediction(
                relevance=a.relevance,
                ai_generated_likelihood=a.ai_generated_likelihood,
                tags=a.tags,
            )
        )
        print(f"  {case.image:32} relevance={a.relevance:.2f} ai={a.ai_generated_likelihood:.2f}")

    report = aggregate(cases, preds)
    report["provider"] = "foundry-model" if used_model else "heuristic-fallback"
    print("\n" + json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
