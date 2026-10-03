"""Missions engine (PRD FR11) — PURE functions, no I/O.

A *mission* is a field task derived from a site that needs a look. The engine
never invents work: it reads the same live signals the attention map already
uses (need score, days unseen, 48 h rain, an open expert flag, the site's check
cadence) and names the most relevant reason to go. This keeps the C3 mission
brief and the Missions tab driven by one authoritative source instead of
client-side heuristics.

The frontend mirrors these rules in ``buildBrief`` as an offline fallback; keep
the two in step.
"""

from __future__ import annotations

from dataclasses import dataclass

# Thresholds (mirror app/scoring.py bands and the front-end buildBrief).
RAIN_MM_TRIGGER = 20.0  # an "after the rain" look is worth it above this
ORPHAN_DAYS = 30  # unseen this long is an orphan site

SAFETY_LINE = "Photo from the bank only. Never wade or touch water near pipes."
STEPS: tuple[str, ...] = ("Observe", "Photograph", "Verify")
EST_MINUTES = "3–5 min"


@dataclass(frozen=True)
class MissionKind:
    """The named reason a site warrants a check, with its brief copy."""

    title: str
    window_label: str
    summary: str


def classify(
    *,
    days_unseen: int,
    rain_48h_mm: float,
    cadence_days: int,
    expert_flag_open: bool,
) -> MissionKind:
    """Pick the single most relevant mission kind for a site.

    Priority: an open expert flag first (a reported problem beats routine work),
    then fresh rain, then a long-unseen orphan, then the cadence coming due,
    then plain monitoring. Exactly one kind is returned so the brief reads
    cleanly.
    """
    if expert_flag_open:
        return MissionKind(
            title="Flag Follow-up Check",
            window_label="Expert flag open",
            summary="A reported issue is open here. A fresh look helps confirm or clear it.",
        )
    if rain_48h_mm >= RAIN_MM_TRIGGER:
        return MissionKind(
            title="After-the-Rain Check",
            window_label=f"{round(rain_48h_mm)} mm rain in 48 h",
            summary="Recent rain can change the water fast. A check now is especially useful.",
        )
    if days_unseen >= ORPHAN_DAYS:
        return MissionKind(
            title="Orphan-Site Check",
            window_label=f"Unseen {days_unseen} days",
            summary="Unseen for over three weeks. Any look revives the record.",
        )
    if days_unseen >= cadence_days:
        return MissionKind(
            title="Cadence Check",
            window_label=f"Open {days_unseen} days · {cadence_days}-day cadence",
            summary="This site is due for its routine check.",
        )
    return MissionKind(
        title="Monitoring Check",
        window_label="Routine monitoring",
        summary="A quick look keeps the record current.",
    )


def warrants_mission(
    *,
    attention: str,
    days_unseen: int,
    rain_48h_mm: float,
    cadence_days: int,
    expert_flag_open: bool,
) -> bool:
    """Whether a site should appear in the suggested-missions list.

    Anything that isn't plainly OK-and-recently-seen is worth surfacing: an open
    flag, fresh rain, a site past its cadence, or any non-``ok`` attention band.
    """
    if expert_flag_open:
        return True
    if rain_48h_mm >= RAIN_MM_TRIGGER:
        return True
    if days_unseen >= cadence_days:
        return True
    return attention != "ok"
