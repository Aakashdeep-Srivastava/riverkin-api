"""Capture-authenticity scoring (PRD anti-cheat) — PURE functions, no I/O.

Combines signals we control (was it captured live in-app, did the upload carry
camera EXIF, is the image perceptually novel vs the site's past photos) with the
vision model's own AI-generated estimate into a single 0–100 confidence that the
photo is a genuine, fresh, on-site capture. Higher = more trustworthy.

This is a *signal*, not a verdict — reliable AI-image detection is unsolved, so
the score is transparent about which factors drove it and humans still decide.
"""

from __future__ import annotations

from dataclasses import dataclass

# pHash Hamming distance at/above which an image is "novel" (not a reuse).
NOVELTY_DISTANCE = 8


@dataclass(frozen=True)
class Authenticity:
    confidence: int  # 0–100, higher = more likely a genuine fresh capture
    reason: str
    factors: dict


def score(
    *,
    captured_live: bool,
    exif_present: bool,
    phash_novelty: int | None,
    model_ai_likelihood: float,
    at_site: bool = False,
) -> Authenticity:
    """Blend provenance + location + model signals into one confidence with a reason."""
    confidence = 50.0
    reasons: list[str] = []

    if captured_live:
        confidence += 25
        reasons.append("captured live in-app")
    elif exif_present:
        confidence += 8
        reasons.append("carried camera metadata")
    else:
        reasons.append("uploaded file")

    # Location: a capture confirmed within the site geofence is strong evidence it
    # is a genuine on-site observation; no confirmed location is a mild unknown.
    if at_site:
        confidence += 12
        reasons.append("confirmed at the site")
    else:
        confidence -= 5
        reasons.append("location not confirmed")

    if phash_novelty is None:
        confidence += 5
        reasons.append("first photo here")
    elif phash_novelty >= NOVELTY_DISTANCE:
        confidence += 15
        reasons.append("visually novel")
    else:
        confidence -= 25
        reasons.append("closely matches an earlier photo")

    model_penalty = max(0.0, min(1.0, model_ai_likelihood)) * 40
    confidence -= model_penalty
    if model_ai_likelihood >= 0.6:
        reasons.append("model flags possible AI generation")
    elif model_ai_likelihood <= 0.35:
        reasons.append("model sees a natural photo")

    clamped = int(max(0, min(100, round(confidence))))
    return Authenticity(
        confidence=clamped,
        reason="; ".join(reasons),
        factors={
            "captured_live": captured_live,
            "exif_present": exif_present,
            "phash_novelty": phash_novelty,
            "model_ai_likelihood": round(float(model_ai_likelihood), 3),
            "at_site": at_site,
        },
    )
