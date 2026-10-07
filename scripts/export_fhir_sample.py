"""Export a representative FHIR Bundle to fhir_sample.json for HL7 validation.

Builds a bundle with app/fhir/bundle.py from synthetic inputs (no DB) so CI can
run the official HL7 FHIR validator against a real, representative artefact. See
the ``fhir-validate`` job in .github/workflows/ci-cd.yml.

    python scripts/export_fhir_sample.py
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.fhir.bundle import build_observation_bundle

OUT = Path(__file__).resolve().parent.parent / "fhir_sample.json"


def main() -> None:
    bundle = build_observation_bundle(
        observation_id=1,
        site_external_id="C1",
        site_name="Exploratório (Mondego)",
        lat=40.19787,
        lng=-8.42865,
        answers={"q-water": "clear", "q-foam": "none", "q-pipe": "yes"},
        feeling="calm",
        status="final",
        verifier_count=3,
        created_at=datetime(2026, 10, 7, 9, 0, tzinfo=UTC),
    )
    OUT.write_text(json.dumps(bundle.model_dump(mode="json"), indent=2), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
