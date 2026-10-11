"""Community feed post — a short, public note shared to the RiverKin feed.

Pseudonymous by design: an author key (the device's RK-XXXX guest id) and a
display name ("Guest" or a Keeper's name). Optionally tied to a site. No images,
no PII — just a short line, so moderation stays light. This is social/community
only and never touches scientific trust or verification.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class CommunityPost(Base):
    __tablename__ = "community_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Pseudonymous device/guest id (RK-XXXX) — lets a device manage its own posts.
    author_key: Mapped[str] = mapped_column(String(64), index=True)
    author_name: Mapped[str] = mapped_column(String(80), default="Guest")
    body: Mapped[str] = mapped_column(String(300))
    # Optional links: the site it's about, and the signed-in author (if any).
    site_id: Mapped[int | None] = mapped_column(
        ForeignKey("sites.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
