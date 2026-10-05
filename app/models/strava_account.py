"""A user's linked Strava account + OAuth tokens.

One row per RiverKin user who has connected Strava (unique user_id). Holds the
rotating Strava access/refresh tokens so the API can pull the athlete's recent
activities ("patrols") on their behalf. Tokens are secrets — never exposed to
the browser; only derived activity data is returned.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class StravaAccount(Base):
    __tablename__ = "strava_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True
    )
    athlete_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    athlete_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    access_token: Mapped[str] = mapped_column(String(128))
    refresh_token: Mapped[str] = mapped_column(String(128))
    # Unix seconds at which the access token expires (Strava's expires_at).
    expires_at: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
