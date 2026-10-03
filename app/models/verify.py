"""Verification models: AI-written verify items and human votes.

The AI only *asks* (writes the item + a weak prior); humans decide by voting
(CLAUDE.md hard rule).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class VerifyItem(Base):
    __tablename__ = "verify_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    observation_id: Mapped[int] = mapped_column(
        ForeignKey("observations.id", ondelete="CASCADE"), index=True
    )
    field_code: Mapped[str] = mapped_column(String(64))
    question: Mapped[str] = mapped_column(String(255))
    ai_box: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Weak AI prior (never fills a field — only nudges trust).
    ai_agrees: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    # Gold-standard items (1 in 5) calibrate verifier reliability.
    is_gold: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    gold_answer: Mapped[str | None] = mapped_column(String(16), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Vote(Base):
    __tablename__ = "votes"

    id: Mapped[int] = mapped_column(primary_key=True)
    verify_item_id: Mapped[int] = mapped_column(
        ForeignKey("verify_items.id", ondelete="CASCADE"), index=True
    )
    voter_kind: Mapped[str] = mapped_column(String(16), default="keeper")
    voter_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    answer: Mapped[str] = mapped_column(String(16))  # yes | no | cant_tell
    ms_taken: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
