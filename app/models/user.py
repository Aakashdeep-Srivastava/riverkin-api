"""User model — adult accounts only (Crew Lead, Keeper, Researcher).

Per the PRD role model + GDPR: no personal accounts for under-16s. Students are
pseudonymous ``crew_members`` inside a Crew Lead's crew, never rows here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32))  # keeper | crew_lead | researcher
    display_name: Mapped[str] = mapped_column(String(128))
    # Adults only — an attestation, never a birthdate (data minimisation).
    age_band: Mapped[str] = mapped_column(String(16), default="18+", server_default="18+")
    large_text: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
