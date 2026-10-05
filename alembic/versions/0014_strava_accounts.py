"""strava accounts (linked runner activities)

Revision ID: 0014_strava_accounts
Revises: 0013_challenges
Create Date: 2026-10-05 10:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_strava_accounts"
down_revision: str | None = "0013_challenges"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strava_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("athlete_id", sa.BigInteger(), nullable=False),
        sa.Column("athlete_name", sa.String(length=128), nullable=True),
        sa.Column("access_token", sa.String(length=128), nullable=False),
        sa.Column("refresh_token", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_strava_accounts_user_id", "strava_accounts", ["user_id"], unique=True
    )
    op.create_index(
        "ix_strava_accounts_athlete_id", "strava_accounts", ["athlete_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_strava_accounts_athlete_id", table_name="strava_accounts")
    op.drop_index("ix_strava_accounts_user_id", table_name="strava_accounts")
    op.drop_table("strava_accounts")
