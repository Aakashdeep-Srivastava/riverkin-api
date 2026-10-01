"""Site model — a monitored water location (OneAquaHealth site).

Minimal placeholder columns only. The full field set (catchment, protection
status, sensor linkage, etc.) comes from the PRD Data model.
"""

from __future__ import annotations

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Site(Base):
    __tablename__ = "sites"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Stable external key from the bundled OAH list (e.g. "oah-0001").
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)

    name: Mapped[str] = mapped_column(String(255))

    # PostGIS point (WGS84). Populated after the geofence check only — never
    # store a raw user GPS fix here (see CLAUDE.md hard rules).
    location: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )

    # Latest computed need score N_s. See app/scoring.py::need_score.
    # TODO(PRD): exact score range, decay, and inputs come from the Algorithms section.
    need_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Flag any seeded/placeholder site as simulated (CLAUDE.md hard rule).
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # TODO(PRD): add catchment id, waterbody type, protection status, risk flags,
    # last_rain_mm, and any denormalised scoring inputs from the PRD Data model.
