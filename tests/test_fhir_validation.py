"""FHIR structural + OAH-IG conformance validation (runs in the CI test job).

This is the always-on, in-process FHIR gate: it builds a bundle, re-parses the
serialized JSON back through the fhir.resources R4B models (which enforces R4B
structural conformance and raises on any violation), and asserts the OneAquaHealth
IG tagging the downstream expects. The heavier official HL7 validator runs as a
separate CI job (see .github/workflows/ci-cd.yml::fhir-validate).
"""

from __future__ import annotations

from datetime import UTC, datetime

from fhir.resources.R4B.bundle import Bundle

from app.fhir.bundle import (
    OAH_CODE_SYSTEM,
    OAH_LOCATION_PROFILE,
    OAH_OBS_PROFILE,
    build_observation_bundle,
)


def _sample() -> Bundle:
    return build_observation_bundle(
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


def test_bundle_roundtrips_through_r4b_models():
    """Serialized bundle re-parses cleanly as R4B (structural validation)."""
    payload = _sample().model_dump(mode="json")
    reparsed = Bundle.model_validate(payload)  # raises on any R4B violation
    assert reparsed.type == "transaction"
    assert reparsed.entry and len(reparsed.entry) >= 5
    # Every transaction entry must carry a request method + url.
    for entry in reparsed.entry:
        assert entry.request is not None
        assert entry.request.method == "POST"
        assert entry.request.url in {"Location", "Group", "Observation", "Provenance"}


def test_bundle_carries_oah_ig_tags():
    payload = _sample().model_dump(mode="json")
    resources = [e["resource"] for e in payload["entry"]]
    by_type: dict[str, list] = {}
    for r in resources:
        by_type.setdefault(r["resourceType"], []).append(r)

    # Location + field Observation declare the OAH IG profiles.
    assert OAH_LOCATION_PROFILE in by_type["Location"][0]["meta"]["profile"]
    field_obs = [
        o for o in by_type["Observation"] if o.get("meta", {}).get("profile") == [OAH_OBS_PROFILE]
    ]
    assert field_obs, "expected at least one OAH-profiled field Observation"
    # Field codes use the real OAH CodeSystem.
    systems = [c["system"] for c in field_obs[0]["code"]["coding"]]
    assert OAH_CODE_SYSTEM in systems


def test_bundle_provenance_has_author_ai_and_verifier():
    payload = _sample().model_dump(mode="json")
    prov = next(
        e["resource"]
        for e in payload["entry"]
        if e["resource"]["resourceType"] == "Provenance"
    )
    roles = {
        a["type"]["coding"][0]["code"] for a in prov["agent"] if a.get("type")
    }
    # "AI asks, humans decide": author (crew), assembler (AI), verifier (community).
    assert {"author", "assembler", "verifier"} <= roles
    assert prov["target"], "Provenance must target the observations"
