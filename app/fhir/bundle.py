"""Minimal FHIR Bundle builder (Observation + Provenance).

This is a deliberately thin stub. The real resource profiles, codes, units,
subject/device references and OAH IG conformance come from the PRD FHIR export
section.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.observation import Observation
from fhir.resources.provenance import Provenance, ProvenanceAgent
from fhir.resources.reference import Reference


def build_observation_bundle(observation_id: int) -> Bundle:
    """Build a minimal transaction Bundle for one observation.

    Contains a placeholder FHIR Observation and a Provenance that targets it.

    TODO(PRD): populate real LOINC/SNOMED codes, Quantity values + UCUM units,
    subject (water body) and performer references, effective time, and shape to
    the OneAquaHealth IG before POSTing to the HAPI server.
    """
    obs_fullurl = f"urn:riverkin:observation:{observation_id}"

    observation = Observation(
        status="preliminary",
        # TODO(PRD): replace placeholder code with the real coded concept.
        code=CodeableConcept(text="RiverKin water observation (placeholder)"),
    )

    provenance = Provenance(
        recorded=datetime.now(UTC),
        target=[Reference(reference=obs_fullurl)],
        agent=[
            ProvenanceAgent(
                # TODO(PRD): real agent (observer / verifier) reference + role.
                who=Reference(display="RiverKin (placeholder agent)")
            )
        ],
    )

    return Bundle(
        type="collection",
        entry=[
            BundleEntry(fullUrl=obs_fullurl, resource=observation),
            BundleEntry(resource=provenance),
        ],
    )
