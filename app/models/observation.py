"""Observation model — a citizen water observation submitted for a site.

Minimal placeholder columns only. The full field set (measured parameters,
photo metadata, verification state machine, FHIR linkage) comes from the PRD.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(primary_key=True)

    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), index=True, nullable=True
    )

    # Verification lifecycle: submitted -> in_verify -> community-verified /
    # queried / expert -> final / amended.
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)

    # OAH protocol answers, keyed by field code (e.g. {"foam": "none", ...}).
    answers: Mapped[dict] = mapped_column(JSONB, default=dict)
    feeling: Mapped[str | None] = mapped_column(String(32), nullable=True)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)

    # A pipe/outfall answer flips the safety flag (routes to expert review).
    pipe_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    geom_ok: Mapped[bool] = mapped_column(Boolean, default=True)

    # Scores (app/scoring.py): quality Q, observation trust T.
    quality: Mapped[float] = mapped_column(Float, default=0.0)
    trust: Mapped[float | None] = mapped_column(Float, nullable=True)
    reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Processed photo (blur/EXIF-stripped) + pHash. No raw GPS ever persisted.
    photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    photo_phash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Days of monitoring gap this check closed (site days_unseen at submit).
    gap_days_closed: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # FHIR Bundle id once exported to HAPI.
    fhir_bundle_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
