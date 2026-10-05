"""Community challenge models (Track 5 growth loop).

Challenges are campaign activities layered over the real OAH sites. Participation
is pseudonymous: a ``participant_key`` is a guest id (``RK-XXXX``) or a signed-in
user's email — no new personal data. Referrals attach a newcomer to the guest who
invited them; the referrer is credited only once, and ONLY in the COMMUNITY
ledger — never in the scientific trust/verification of any observation.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Challenge(Base):
    __tablename__ = "challenges"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)  # slug
    title: Mapped[str] = mapped_column(String(128))
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(24))  # run|check|biodiversity|pollution|map
    meta: Mapped[str] = mapped_column(String(48), default="", server_default="")
    window: Mapped[str] = mapped_column(String(48), default="This week", server_default="This week")
    status: Mapped[str] = mapped_column(String(16), default="live", server_default="live")
    days_left: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    sites: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    blurb: Mapped[str] = mapped_column(Text, default="", server_default="")
    credit: Mapped[int] = mapped_column(Integer, default=100, server_default="100")
    featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Existing campaign participants (seeded); live joined = base_joined + real participants.
    base_joined: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ChallengeParticipant(Base):
    __tablename__ = "challenge_participants"
    __table_args__ = (
        UniqueConstraint("challenge_id", "participant_key", name="uq_challenge_participant"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[str] = mapped_column(
        ForeignKey("challenges.id", ondelete="CASCADE"), index=True
    )
    participant_key: Mapped[str] = mapped_column(String(64), index=True)
    reports_submitted: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Referral(Base):
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("referred_key", name="uq_referred_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    referrer_key: Mapped[str] = mapped_column(String(64), index=True)
    referred_key: Mapped[str] = mapped_column(String(64), index=True)
    # Credited once the referred person actually joins a challenge.
    credited: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
