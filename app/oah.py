"""Interpretation of real OneAquaHealth baseline values.

Pure functions (no I/O): turn the raw OAH snapshots stored on ``Site.ecology``
and ``Site.health_risk`` into the bands/labels the API exposes. Values are the
project's own data from api.enora-oah.eu (see data/DATA_PROVENANCE.md); we only
classify them, never invent them.
"""

from __future__ import annotations

# Water Framework Directive ecological status classes, best → worst.
# "One out, all out": a water body's status is its worst quality element.
_WFD_ORDER = ["High", "Good", "Moderate", "Poor", "Bad"]
_WFD_RANK = {name: i for i, name in enumerate(_WFD_ORDER)}

# Band → display colour (aligned with the web attention palette).
_WFD_COLOR = {
    "High": "#2FA36B",
    "Good": "#73B56B",
    "Moderate": "#F2A93B",
    "Poor": "#E88A3C",
    "Bad": "#E5484D",
}


def _clean(value: object) -> str | None:
    """Normalise a WFD class string; treat ``""``/None/unknown as absent."""
    if not isinstance(value, str):
        return None
    v = value.strip().title()
    return v if v in _WFD_RANK else None


def ecology_status(ecology: dict | None) -> dict | None:
    """Roll the biological/chemical elements up to one worst-case status.

    Returns ``{status, color, worst_element, elements[], nitrate, date}`` or
    ``None`` when no quality class is available.
    """
    if not ecology:
        return None

    elements: list[dict] = []
    pairs = [
        ("macroinvertebrates", "macroinvertebratesQuality", "macroinvertebratesRichness"),
        ("diatoms", "diatomsQuality", "diatomsRichness"),
        ("fish", "fishQuality", "fishRichness"),
    ]
    worst: str | None = None
    worst_label: str | None = None
    for label, qkey, rkey in pairs:
        cls = _clean(ecology.get(qkey))
        richness = ecology.get(rkey)
        if cls is None and richness is None:
            continue
        elements.append({"element": label, "quality": cls, "richness": richness})
        if cls is not None and (worst is None or _WFD_RANK[cls] > _WFD_RANK[worst]):
            worst, worst_label = cls, label

    if worst is None and not elements:
        return None

    return {
        "status": worst,
        "color": _WFD_COLOR.get(worst or "", "#C9CED8"),
        "worst_element": worst_label,
        "elements": elements,
        "nitrate": ecology.get("nitrate"),
        "date": ecology.get("date"),
    }


def health_risk_band(health_risk: dict | None) -> dict | None:
    """Classify the composite One Health risk score (0–1) into low/moderate/high."""
    if not health_risk:
        return None
    score = health_risk.get("score")
    if score is None:
        return None
    score = float(score)
    if score < 0.33:
        band, color = "low", "#2FA36B"
    elif score < 0.66:
        band, color = "moderate", "#F2A93B"
    else:
        band, color = "high", "#E5484D"
    return {
        "score": round(score, 4),
        "band": band,
        "color": color,
        "pathogen": health_risk.get("pathogen"),
        "fecal": health_risk.get("fecal"),
        "arg": health_risk.get("arg"),
        "date": health_risk.get("date"),
    }
