"""Site model — a monitored water location (OneAquaHealth site).

Minimal placeholder columns only. The full field set (catchment, protection
status, sensor linkage, etc.) comes from the PRD Data model.
"""

from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Stable OAH site code from the bundled list (e.g. "CB-01", "BN-04").
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    name: Mapped[str] = mapped_column(String(255))

    # Real OneAquaHealth context.
    waterbody: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(128), index=True, nullable=True)
    country: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # Convenience lat/lng (WGS84) for the API response; the geometry below is the
    # spatial source of truth for ST_DWithin geofence queries.
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    altitude_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    location: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )

    # Real OneAquaHealth baseline snapshots (latest sample), stored verbatim:
    # ecology = biological + chemical quality (macroinvertebrates/diatoms/fish/nitrate);
    # health_risk = One Health risk scores (pathogen/fecal/ARG + composite).
    # Source: api.enora-oah.eu. See data/DATA_PROVENANCE.md.
    ecology: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    health_risk: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Real keyless open-data signal snapshots, refreshed by app/jobs/scheduled.py
    # and cached here (like rain_48h_mm). biodiversity = GBIF freshwater
    # bioindicator richness within 5 km; discharge = GloFAS river discharge m³/s.
    # Shapes are produced by app/signals.py. See data/DATA_PROVENANCE.md.
    biodiversity: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    discharge: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Scoring inputs (denormalised; recomputed by the rain/need job).
    cadence_days: Mapped[int] = mapped_column(Integer, default=14, server_default="14")
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rain_48h_mm: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    expert_flag_open: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )

    # Latest computed need score N_s (app/scoring.py::need_score).
    need_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Flag any seeded/placeholder site as simulated (CLAUDE.md hard rule).
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
