"""Crew models — Crew Lead accounts, pseudonymous members, site adoptions and
field-safety check-ins (PRD Data model: crews, crew_members, adoptions, checkins).

Students are never rows in ``users``; they exist only as pseudonymous handles in
``crew_members`` inside a Crew Lead's crew (PRD role model + GDPR minimisation).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Crew(Base):
    __tablename__ = "crews"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    city: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # A minor crew (under-16) requires an active Crew Lead check-in to start a check.
    is_minor_crew: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    streak_windows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    freezes_left: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CrewMember(Base):
    __tablename__ = "crew_members"

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id", ondelete="CASCADE"), index=True)
    handle: Mapped[str] = mapped_column(String(64))  # e.g. "Scout 3" — no personal data
    role_this_week: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Adoption(Base):
    __tablename__ = "adoptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id", ondelete="CASCADE"), index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    adopted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Checkin(Base):
    __tablename__ = "checkins"

    id: Mapped[int] = mapped_column(primary_key=True)
    crew_id: Mapped[int] = mapped_column(ForeignKey("crews.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Active window: a check-in is valid for 90 minutes (PRD).
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
