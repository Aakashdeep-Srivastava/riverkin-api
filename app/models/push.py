"""Web Push subscription — a browser's push endpoint + keys.

Stored so the scheduled job can send after-rain / coverage nudges (the Track-5
reactivation loop). Pseudonymous: no personal data, optional user link.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(512), unique=True, index=True)
    p256dh: Mapped[str] = mapped_column(String(256))
    auth: Mapped[str] = mapped_column(String(128))
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
