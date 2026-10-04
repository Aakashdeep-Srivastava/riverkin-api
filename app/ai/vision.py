"""Vision analysis for observation photos (PRD AI service — "AI asks").

Analyses a captured river photo with a small, low-cost Azure AI Foundry vision
model: a short scene summary, scene tags, and the model's own estimate of how
likely the image is AI-generated. This is only ever a *weak prior / signal* —
humans still decide (PRD). When Foundry is not configured (no endpoint/key) a
deterministic analysis derived from image statistics is returned instead, so the
field-check flow always works offline and in CI.
"""

from __future__ import annotations

import base64
import io
import json
from dataclasses import dataclass, field

import httpx
import numpy as np
from PIL import Image

from app.config import settings

# The model returns a WEAK, structured per-field read aligned to the citizen's
# check — never a verdict. "AI asks, humans decide" (CLAUDE.md). Each field
# carries the model's own confidence so a low-confidence read is ignored.
PROMPT = (
    "You are assisting a citizen river-monitoring app. Look at this photo of a "
    "stream or river taken from the bank. Respond ONLY with compact JSON:\n"
    '{"summary": string (<=140 chars), '
    '"tags": string[] (up to 5 short labels), '
    '"relevance": number 0..1 (is this an in-focus photo of a river/stream and '
    'its bank, not a selfie/unrelated scene), '
    '"ai_generated_likelihood": number 0..1, '
    '"fields": {'
    '"water_appearance": {"value": "clear|slightly_turbid|turbid", "confidence": 0..1, '
    '"question": string}, '
    '"foam": {"value": "none|some|lots", "confidence": 0..1, "question": string}, '
    '"litter": {"value": "none|some|lots", "confidence": 0..1, "question": string}, '
    '"pipe_outfall": {"value": "none|visible", "confidence": 0..1, "question": string}, '
    '"flow": {"value": "low|normal|high", "confidence": 0..1, "question": string}, '
    '"bank_vegetation": {"value": "bare|some|lush", "confidence": 0..1, "question": string}'
    "}}. "
    'Each "question" is a short, natural yes/no-style question a volunteer could '
    "answer by looking at THIS photo, grounded in what you actually see (e.g. "
    "\"Is there white foam near the right bank?\" or \"Does the water look muddy "
    'here?"). Vary it to fit the scene. '
    "Set a field's confidence to 0 if you genuinely cannot tell from the image. "
    "No prose, JSON only."
)

# Fields the model may estimate (keys in VisionAnalysis.fields).
ASSESSABLE_FIELDS = (
    "water_appearance",
    "foam",
    "litter",
    "pipe_outfall",
    "flow",
    "bank_vegetation",
)


@dataclass(frozen=True)
class VisionAnalysis:
    summary: str
    tags: list[str] = field(default_factory=list)
    ai_generated_likelihood: float = 0.5
    relevance: float = 0.5
    # {field_key: {"value": str, "confidence": float}} — a weak per-field prior.
    fields: dict[str, dict] = field(default_factory=dict)
    model: str = "heuristic"
    used_model: bool = False


def _data_uri(raw: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def _heuristic(raw: bytes) -> VisionAnalysis:
    """Deterministic scene read from image statistics (no network).

    Not a substitute for a real model — it gives the demo a sensible,
    reproducible analysis when Foundry is unconfigured, and a neutral AI-likelihood
    (the provenance signals carry authenticity in that case).
    """
    try:
        pil = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return VisionAnalysis(summary="Photo received.", tags=[], model="heuristic")

    arr = np.asarray(pil.resize((64, 64))).astype("float32")
    r, g, b = arr[..., 0].mean(), arr[..., 1].mean(), arr[..., 2].mean()
    brightness = float(arr.mean())
    greenish = g > r and g > b
    brownish = r > b and g > b and r > 90
    tags: list[str] = []
    if greenish:
        tags.append("vegetation-or-algae")
    if brownish:
        tags.append("turbid-or-muddy")
    if brightness > 150:
        tags.append("bright")
    elif brightness < 70:
        tags.append("low-light")
    if not tags:
        tags.append("normal")

    summary = (
        "Water surface with "
        + ("greener tones (vegetation or algae)" if greenish else "")
        + ("brown/turbid tones" if brownish and not greenish else "")
        + ("balanced tones" if not greenish and not brownish else "")
        + f", {'bright' if brightness > 150 else 'dim' if brightness < 70 else 'even'} light."
    )
    # Coarse, low-confidence field reads from colour stats. These are only a weak
    # prior; real distinctions need the configured model. Confidence stays low so
    # the heuristic rarely overrides the human.
    fields: dict[str, dict] = {
        "water_appearance": {
            "value": "turbid" if brownish else "clear",
            "confidence": 0.3,
        },
        "bank_vegetation": {"value": "lush" if greenish else "some", "confidence": 0.2},
    }
    return VisionAnalysis(
        summary=summary,
        tags=tags,
        ai_generated_likelihood=0.5,
        relevance=0.6,
        fields=fields,
        model="heuristic",
    )


def _parse_model_json(text: str) -> dict:
    """Pull the JSON object out of a model reply that may wrap it in prose/fences."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no json object in reply")
    return json.loads(text[start : end + 1])


async def analyze_image(raw: bytes) -> VisionAnalysis:
    """Analyse a photo with Foundry if configured, else the heuristic fallback."""
    endpoint = settings.FOUNDRY_VISION_ENDPOINT.rstrip("/")
    key = settings.FOUNDRY_VISION_KEY
    if not endpoint or not key:
        return _heuristic(raw)

    body = {
        "model": settings.FOUNDRY_VISION_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {"type": "image_url", "image_url": {"url": _data_uri(raw)}},
                ],
            }
        ],
        "max_tokens": 300,
        "temperature": 0.0,
    }
    url = f"{endpoint}/chat/completions?api-version={settings.FOUNDRY_API_VERSION}"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                url,
                headers={"api-key": key, "Content-Type": "application/json"},
                json=body,
            )
        if resp.status_code != 200:
            return _heuristic(raw)
        content = resp.json()["choices"][0]["message"]["content"]
        data = _parse_model_json(content if isinstance(content, str) else str(content))
    except Exception:
        return _heuristic(raw)

    def _num(v: object, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(v)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    likelihood = _num(data.get("ai_generated_likelihood"), 0.5)
    relevance = _num(data.get("relevance"), 0.5)
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    # Parse the structured per-field reads, keeping only well-formed entries.
    raw_fields = data.get("fields") or {}
    fields: dict[str, dict] = {}
    if isinstance(raw_fields, dict):
        for key in ASSESSABLE_FIELDS:
            entry = raw_fields.get(key)
            if isinstance(entry, dict) and entry.get("value") is not None:
                fields[key] = {
                    "value": str(entry["value"])[:24],
                    "confidence": _num(entry.get("confidence"), 0.0),
                }
                q = entry.get("question")
                if isinstance(q, str) and q.strip():
                    fields[key]["question"] = q.strip()[:160]

    return VisionAnalysis(
        summary=str(data.get("summary") or "Water surface photographed from the bank.")[:200],
        tags=[str(t)[:32] for t in tags[:5]],
        ai_generated_likelihood=likelihood,
        relevance=relevance,
        fields=fields,
        model=settings.FOUNDRY_VISION_MODEL,
        used_model=True,
    )
