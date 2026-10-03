"""FHIR R4 Bundle builder shaped to the OneAquaHealth IG.

Each field check becomes one transaction Bundle: a Location (the OAH site), a
pseudonymous crew Group, one Observation per answered OAH field, an optional
wellbeing Observation for the feeling, and a Provenance recording who did what
(crew author, AI assistant Device, aggregated verifier Group, expert).

Uses the R4B models (the OAH IG is R4). This builds a structurally valid R4
resource; full HL7-validator conformance against the IG package runs in CI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fhir.resources.R4B.bundle import Bundle, BundleEntry, BundleEntryRequest
from fhir.resources.R4B.codeableconcept import CodeableConcept
from fhir.resources.R4B.coding import Coding
from fhir.resources.R4B.group import Group
from fhir.resources.R4B.identifier import Identifier
from fhir.resources.R4B.location import Location, LocationPosition
from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.provenance import Provenance, ProvenanceAgent
from fhir.resources.R4B.reference import Reference

from app.ai.questions import FIELD_SPECS

# OAH IG identifiers (real CodeSystem; profile URLs best-effort to the IG).
OAH_CODE_SYSTEM = "http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu"
OAH_ANSWER_SYSTEM = "http://hl7.eu/fhir/ig/oah/CodeSystem/temporarySystem-oah-eu-answers"
OAH_OBS_PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/oah-observation"
OAH_LOCATION_PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/oah-location"
RK_DEVICE = "urn:riverkin:device:vlm-assistant"

# q-* answer key -> (oah_code, display) from app/ai/questions.py::FIELD_SPECS.
_FIELD_BY_KEY = {s["key"]: s for s in FIELD_SPECS}


def _obs_status(observation_status: str) -> str:
    """Map the RiverKin lifecycle to a FHIR Observation.status."""
    if observation_status == "final":
        return "final"
    if observation_status == "amended":
        return "amended"
    if observation_status in ("queried", "expert"):
        return "preliminary"
    return "preliminary"


def _field_observation(
    *,
    obs_id: int,
    key: str,
    value: str,
    status: str,
    location_url: str,
    group_url: str,
    when: datetime,
) -> tuple[str, Observation]:
    spec = _FIELD_BY_KEY.get(key, {"field_code": key, "label": key})
    full_url = f"urn:riverkin:observation:{obs_id}:{spec['field_code']}"
    obs = Observation(
        meta={"profile": [OAH_OBS_PROFILE]},
        status=_obs_status(status),
        category=[
            CodeableConcept(
                coding=[
                    Coding(
                        system="http://terminology.hl7.org/CodeSystem/observation-category",
                        code="environment",
                        display="Environment",
                    )
                ]
            )
        ],
        code=CodeableConcept(
            coding=[
                Coding(system=OAH_CODE_SYSTEM, code=spec["field_code"], display=spec["label"])
            ],
            text=spec["label"],
        ),
        valueCodeableConcept=CodeableConcept(
            coding=[Coding(system=OAH_ANSWER_SYSTEM, code=value)],
            text=value.replace("_", " "),
        ),
        subject=Reference(reference=location_url),
        effectiveDateTime=when,
        performer=[Reference(reference=group_url)],
    )
    return full_url, obs


def _wellbeing_observation(
    *, obs_id: int, feeling: str, location_url: str, group_url: str, when: datetime
) -> tuple[str, Observation]:
    full_url = f"urn:riverkin:observation:{obs_id}:wellbeing"
    obs = Observation(
        status="preliminary",
        category=[
            CodeableConcept(
                coding=[
                    Coding(
                        system="http://terminology.hl7.org/CodeSystem/observation-category",
                        code="survey",
                        display="Survey",
                    )
                ],
                text="wellbeing perception",
            )
        ],
        code=CodeableConcept(text="Wellbeing perception at the river"),
        valueCodeableConcept=CodeableConcept(text=feeling),
        subject=Reference(reference=location_url),
        effectiveDateTime=when,
        performer=[Reference(reference=group_url)],
    )
    return full_url, obs


def _entry(full_url: str, resource: Any, resource_type: str) -> BundleEntry:
    return BundleEntry(
        fullUrl=full_url,
        resource=resource,
        request=BundleEntryRequest(method="POST", url=resource_type),
    )


def build_observation_bundle(
    *,
    observation_id: int,
    site_external_id: str | None,
    site_name: str,
    lat: float | None,
    lng: float | None,
    answers: dict[str, str],
    feeling: str | None,
    status: str,
    verifier_count: int,
    created_at: datetime | None = None,
) -> Bundle:
    """Build a transaction Bundle (Location + Group + Observations + Provenance)."""
    when = created_at or datetime.now(UTC)
    location_url = f"urn:riverkin:location:{site_external_id or observation_id}"
    group_url = f"urn:riverkin:group:crew:{observation_id}"

    location = Location(
        meta={"profile": [OAH_LOCATION_PROFILE]},
        identifier=[
            Identifier(system=OAH_CODE_SYSTEM, value=site_external_id or str(observation_id))
        ],
        name=site_name,
        position=(
            LocationPosition(longitude=lng, latitude=lat)
            if lat is not None and lng is not None
            else None
        ),
    )
    crew = Group(type="person", actual=True, quantity=1)

    entries: list[BundleEntry] = [
        _entry(location_url, location, "Location"),
        _entry(group_url, crew, "Group"),
    ]
    observation_urls: list[str] = []

    for key, value in answers.items():
        if not value:
            continue
        full_url, obs = _field_observation(
            obs_id=observation_id,
            key=key,
            value=value,
            status=status,
            location_url=location_url,
            group_url=group_url,
            when=when,
        )
        entries.append(_entry(full_url, obs, "Observation"))
        observation_urls.append(full_url)

    if feeling:
        full_url, obs = _wellbeing_observation(
            obs_id=observation_id,
            feeling=feeling,
            location_url=location_url,
            group_url=group_url,
            when=when,
        )
        entries.append(_entry(full_url, obs, "Observation"))
        observation_urls.append(full_url)

    provenance = Provenance(
        recorded=when,
        target=(
            [Reference(reference=u) for u in observation_urls]
            or [Reference(reference=location_url)]
        ),
        activity=CodeableConcept(
            coding=[
                Coding(
                    system="http://terminology.hl7.org/CodeSystem/v3-DataOperation",
                    code="CREATE",
                    display="create",
                )
            ],
            text="collection, verification"
            if verifier_count
            else "collection",
        ),
        agent=[
            ProvenanceAgent(
                type=CodeableConcept(
                    coding=[
                        Coding(
                            system="http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                            code="author",
                        )
                    ]
                ),
                who=Reference(reference=group_url, display="RiverKin crew (pseudonymous)"),
            ),
            ProvenanceAgent(
                type=CodeableConcept(
                    coding=[
                        Coding(
                            system="http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                            code="assembler",
                        )
                    ]
                ),
                who=Reference(
                    reference=RK_DEVICE,
                    display="RiverKin AI (assistant; asks, never decides)",
                ),
            ),
            ProvenanceAgent(
                type=CodeableConcept(
                    coding=[
                        Coding(
                            system="http://terminology.hl7.org/CodeSystem/provenance-participant-type",
                            code="verifier",
                        )
                    ]
                ),
                who=Reference(display=f"Community verifiers (n={verifier_count})"),
            ),
        ],
    )
    entries.append(_entry(f"urn:riverkin:provenance:{observation_id}", provenance, "Provenance"))

    return Bundle(type="transaction", entry=entries)
