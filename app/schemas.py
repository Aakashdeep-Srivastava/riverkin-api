"""Pydantic response models for the public API."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


# ============================================================
# Auth (adult accounts)
# ============================================================
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    role: str = "keeper"  # keeper | crew_lead | researcher
    large_text: bool = False


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    display_name: str
    large_text: bool


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SiteOut(BaseModel):
    """A monitored OAH site with its current attention state.

    ``id`` is the stable OAH code (string) so the front end can route on it.
    """

    id: str
    name: str
    waterbody: str | None = None
    city: str | None = None
    country: str | None = None
    lat: float | None = None
    lng: float | None = None
    altitude_m: float | None = None
    days_unseen: int
    rain_48h_mm: float
    need_score: float
    attention: str
    color: str
    # Real OneAquaHealth baseline (classified by app/oah.py); null when the site
    # has no published sample. See ``data_attribution``.
    ecology: dict | None = None
    health_risk: dict | None = None
    # Coordinates, identity and ecology/health are REAL (from OAH). Only the
    # "days since last citizen check" schedule is illustrative — hence this flag.
    recency_simulated: bool = True
    data_attribution: str | None = None
    simulated: bool = True


class TimelineEntry(BaseModel):
    kind: str
    label: str
    at: str


class SiteTimelineOut(BaseModel):
    site_id: str
    entries: list[TimelineEntry]
    simulated: bool = True


# ============================================================
# Missions (FR11) — field tasks derived from sites needing attention
# ============================================================


class MissionOut(BaseModel):
    """A suggested field mission for the Missions tab list."""

    id: str
    site_id: str
    site_name: str
    waterbody: str | None = None
    city: str | None = None
    title: str
    summary: str
    attention: str
    color: str
    need_score: float
    days_unseen: int
    distance_km: float | None = None
    simulated: bool = True


class MissionBriefOut(BaseModel):
    """The C3 mission brief for a single site."""

    id: str
    site_id: str
    site_name: str
    waterbody: str | None = None
    city: str | None = None
    name: str
    window_label: str
    est_minutes: str
    safety_line: str
    steps: list[str]
    attention: str
    color: str
    need_score: float
    days_unseen: int
    rain_48h_mm: float
    distance_km: float | None = None
    simulated: bool = True


# ============================================================
# Observations (Perfect 6 #3 + #5)
# ============================================================
class ObservationIn(BaseModel):
    """Field-check submission from C4.

    ``answers`` is keyed by the front-end question id (``q-water`` …), which
    maps to the OAH field codes in app/ai/questions.py::FIELD_SPECS. ``lat``/
    ``lng`` are used once for the geofence check and then discarded — raw GPS is
    never persisted (PRD privacy rule).
    """

    site_code: str
    answers: dict[str, str] = {}
    feeling: str | None = None
    photo_count: int = 0
    lat: float | None = None
    lng: float | None = None


class ReceiptPhotoOut(BaseModel):
    """The analysed check photo shown on the receipt."""

    url: str
    summary: str
    tags: list[str] = []
    model: str
    used_model: bool
    ai_generated_likelihood: float
    authenticity: int
    authenticity_reason: str
    captured_live: bool
    geotag_label: str | None = None
    lat: float | None = None
    lng: float | None = None
    # Image-grounded cross-check of the citizen's answers vs the photo.
    relevance: float | None = None
    correlation: list[dict] = []
    escalated: bool = False


class ReceiptOut(BaseModel):
    """Impact receipt rendered on C6."""

    site_name: str
    waterbody: str
    city: str
    gap_before: int
    gap_after: int
    rain_context: str
    verifier_count: int
    fhir_id: str | None
    sentinel_line: str
    state: str
    date_label: str
    points: int = 0  # River points earned for this check (River Value)
    photo: ReceiptPhotoOut | None = None


class ObservationCreated(BaseModel):
    """Response to POST /observations — the new id + first receipt."""

    id: int
    status: str
    verify_item_count: int
    receipt: ReceiptOut
    simulated: bool = True


class ObservationStatusOut(BaseModel):
    """GET /observations/{id}/status — live trust + receipt."""

    id: int
    status: str
    trust: float | None
    verifier_count: int
    receipt: ReceiptOut
    simulated: bool = True


# ============================================================
# Verify rounds (Perfect 6 #4)
# ============================================================
class VerifyCard(BaseModel):
    """One verify card for C5. Submitter, tally and gold status are hidden."""

    item_id: int
    observation_id: int
    site_name: str
    field_code: str
    question: str
    ai_box: str | None = None


class VerifyNextOut(BaseModel):
    cards: list[VerifyCard]
    simulated: bool = True


class VoteIn(BaseModel):
    answer: str  # yes | no | cant_tell
    ms_taken: int | None = None
    voter_kind: str = "keeper"  # keeper | member | researcher
    voter_id: str | None = None


class VoteResult(BaseModel):
    recorded: bool
    observation_id: int
    observation_status: str
    trust: float | None
    simulated: bool = True
