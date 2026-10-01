"""Observation model — a citizen water observation submitted for a site.

Minimal placeholder columns only. The full field set (measured parameters,
photo metadata, verification state machine, FHIR linkage) comes from the PRD.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True)

    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # Lifecycle status. TODO(PRD): replace with the exact verification state
    # machine (submitted -> in_verify -> verified/rejected -> exported).
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)

    # Blob path of the processed (blurred, EXIF-stripped) photo. No raw GPS or
    # unprocessed image is ever persisted (CLAUDE.md hard rules).
    photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Perceptual hash (pHash) of the processed photo, for dedup.
    photo_phash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Latest computed reliability score for this observation.
    # TODO(PRD): exact formula in app/scoring.py::reliability_score.
    reliability_score: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # TODO(PRD): add observer_id, measured parameters (turbidity, flow, etc.),
    # safety_reason, FHIR resource id, and verification round linkage.
