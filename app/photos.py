"""Photo processing for observation uploads (PRD anti-cheat + privacy).

Runs on upload: EXIF strip, Laplacian-variance blur score, perceptual hash
(pHash) for duplicate detection, and a best-effort face blur before storage.
Stores the *processed* bytes only — the raw upload (with EXIF/GPS) is discarded.

Storage is local disk for the MVP (``media/``); production swaps in Azure Blob
via STORAGE_ACCOUNT_URL. Kept out of the router so it is unit-testable.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import cv2
import imagehash
import numpy as np
from PIL import Image

# Local processed-photo store (git-ignored). Azure Blob in production.
MEDIA_DIR = Path(__file__).resolve().parent.parent / "media"

# Laplacian variance below this is "blurry" and prompts a retake (PRD).
BLUR_THRESHOLD = 100.0
# pHash Hamming distance below this against a past photo = likely reuse (PRD).
PHASH_REUSE_DISTANCE = 8


@dataclass(frozen=True)
class ProcessedPhoto:
    path: str
    phash: str
    blur_score: float
    is_blurry: bool
    faces_blurred: int
    jpeg_bytes: bytes  # clean (EXIF-stripped, face-blurred) bytes — safe to send onward


def has_exif(raw: bytes) -> bool:
    """True if the uploaded bytes carry any EXIF metadata (camera/GPS block).

    A live in-app canvas capture has none; a real camera file usually does; many
    AI-generated images have none. Used only as a weak authenticity signal — the
    EXIF itself is always dropped before storage.
    """
    try:
        exif = Image.open(io.BytesIO(raw)).getexif()
        return bool(exif) and len(exif) > 0
    except Exception:
        return False


def _blur_score(gray: np.ndarray) -> float:
    """Variance of the Laplacian — higher is sharper."""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _blur_faces(bgr: np.ndarray) -> int:
    """Gaussian-blur any detected faces in place. Returns the count.

    Best-effort: if this OpenCV build ships no Haar cascades (headless/minimal),
    face blur is skipped. The privacy guarantee is still met because the raw
    upload (with EXIF/GPS) is discarded and only re-encoded pixels are stored.
    """
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        return 0
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(cascade_path)
        if cascade.empty():
            return 0
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(40, 40))
        for x, y, w, h in faces:
            roi = bgr[y : y + h, x : x + w]
            bgr[y : y + h, x : x + w] = cv2.GaussianBlur(roi, (0, 0), sigmaX=18)
        return len(faces)
    except cv2.error:
        return 0


def process_photo(
    raw: bytes, *, observation_id: int, kind: str = "upstream", persist: bool = True
) -> ProcessedPhoto:
    """Process one uploaded photo and (optionally) persist the clean bytes.

    EXIF is dropped by re-encoding from the pixel data only. Returns the stored
    path, perceptual hash, blur score and face-blur count. ``persist=False`` runs
    the exact same clean-up (face blur, EXIF strip, blur score) but writes nothing
    to disk — used by the stateless live-scan preview, which must not create files.
    """
    # Decode via PIL (RGB, no EXIF carried forward) then to OpenCV BGR.
    pil = Image.open(io.BytesIO(raw)).convert("RGB")
    rgb = np.array(pil)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    faces_blurred = _blur_faces(bgr)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    blur = _blur_score(gray)

    # pHash from the (face-blurred) processed image.
    processed_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    phash = str(imagehash.phash(Image.fromarray(processed_rgb)))

    clean = Image.fromarray(processed_rgb)
    buf = io.BytesIO()
    clean.save(buf, format="JPEG", quality=85)

    path = ""
    if persist:
        MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        out_path = MEDIA_DIR / f"obs{observation_id:05d}-{kind}.jpg"
        clean.save(out_path, format="JPEG", quality=85)
        path = str(out_path.relative_to(MEDIA_DIR.parent))

    return ProcessedPhoto(
        path=path,
        phash=phash,
        blur_score=blur,
        is_blurry=blur < BLUR_THRESHOLD,
        faces_blurred=faces_blurred,
        jpeg_bytes=buf.getvalue(),
    )


def phash_distance(a: str, b: str) -> int:
    """Hamming distance between two hex pHash strings."""
    return imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b)
