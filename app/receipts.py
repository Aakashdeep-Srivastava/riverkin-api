"""Impact-receipt + status-label helpers (PRD C6 / FR7).

Pure, deterministic functions so the receipt is unit-testable and the demo is
reproducible. The receipt "states exactly what the visit changed": the gap it
closed, the rain context, the verifier count and a single Sentinel line citing
the field that triggered it.
"""

from __future__ import annotations

from datetime import datetime

from app import scoring

_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def date_label(dt: datetime | None) -> str:
    """Cross-platform receipt date like ``3 Oct 2026 · 14:23`` (no %-d)."""
    if dt is None:
        return ""
    return f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year} · {dt:%H:%M}"

# Status → human-facing receipt state label.
STATE_LABELS: dict[str, str] = {
    "submitted": "Submitted",
    "in_verify": "In peer verification",
    "pending": "In peer verification",
    "community-verified": "Community verified",
    "queried": "Queried — needs another look",
    "expert": "Sent for expert review",
    "final": "Expert confirmed",
    "amended": "Expert amended",
}


def state_label(status: str) -> str:
    """Human label for an observation status (C6)."""
    return STATE_LABELS.get(status, "In peer verification")


def rain_context(rain_48h_mm: float) -> str:
    """One-line rain context for the receipt."""
    if rain_48h_mm >= scoring.RAIN_THRESHOLD_MM:
        return f"First verified check after {round(rain_48h_mm)} mm of rain"
    if rain_48h_mm > 0:
        return f"Logged with {round(rain_48h_mm)} mm of recent rain in context"
    return "Logged on the site's 14-day monitoring cadence"


def sentinel_line(answers: dict[str, str]) -> str:
    """One Sentinel flavour line citing the field that triggered it (PRD).

    Sombra the alder speaks for the bank/vegetation; Zumbido the mosquito speaks
    for water quality signals (foam, litter). Deterministic from the answers.
    """
    foam = answers.get("q-foam")
    litter = answers.get("q-litter")
    water = answers.get("q-water")
    if foam in ("patches", "lots"):
        return 'Zumbido: "Foam on the surface caught my eye — worth another look."'
    if litter in ("some", "a_lot"):
        return 'Zumbido: "Some litter by the bank. Every report helps clear it."'
    if water in ("clear",):
        return 'Sombra: "The water ran clear today, so I\'m content."'
    return 'Sombra: "Plant cover held the bank well. The reach looks cared for."'


def fhir_short_id(observation_id: int) -> str:
    """Stable short FHIR id shown on the receipt (e.g. ``rk-a0012``)."""
    return f"rk-{observation_id:05d}"
