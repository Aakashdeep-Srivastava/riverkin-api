"""community challenges, participants and referrals

Revision ID: 0013_challenges
Revises: 0012_events
Create Date: 2026-10-05 06:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013_challenges"
down_revision: str | None = "0012_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "challenges",
        sa.Column("id", sa.String(length=48), primary_key=True),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("city", sa.String(length=64), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("meta", sa.String(length=48), server_default="", nullable=False),
        sa.Column("window", sa.String(length=48), server_default="This week", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="live", nullable=False),
        sa.Column("days_left", sa.Integer(), server_default="7", nullable=False),
        sa.Column("sites", sa.Integer(), server_default="5", nullable=False),
        sa.Column("blurb", sa.Text(), server_default="", nullable=False),
        sa.Column("credit", sa.Integer(), server_default="100", nullable=False),
        sa.Column("featured", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("base_joined", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sort", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "challenge_participants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "challenge_id",
            sa.String(length=48),
            sa.ForeignKey("challenges.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("participant_key", sa.String(length=64), nullable=False),
        sa.Column("reports_submitted", sa.Integer(), server_default="0", nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("challenge_id", "participant_key", name="uq_challenge_participant"),
    )
    op.create_index(
        "ix_challenge_participants_challenge_id", "challenge_participants", ["challenge_id"]
    )
    op.create_index(
        "ix_challenge_participants_participant_key", "challenge_participants", ["participant_key"]
    )

    op.create_table(
        "referrals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("referrer_key", sa.String(length=64), nullable=False),
        sa.Column("referred_key", sa.String(length=64), nullable=False),
        sa.Column("credited", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("referred_key", name="uq_referred_key"),
    )
    op.create_index("ix_referrals_referrer_key", "referrals", ["referrer_key"])
    op.create_index("ix_referrals_referred_key", "referrals", ["referred_key"])


def downgrade() -> None:
    op.drop_index("ix_referrals_referred_key", table_name="referrals")
    op.drop_index("ix_referrals_referrer_key", table_name="referrals")
    op.drop_table("referrals")
    op.drop_index(
        "ix_challenge_participants_participant_key", table_name="challenge_participants"
    )
    op.drop_index(
        "ix_challenge_participants_challenge_id", table_name="challenge_participants"
    )
    op.drop_table("challenge_participants")
    op.drop_table("challenges")
