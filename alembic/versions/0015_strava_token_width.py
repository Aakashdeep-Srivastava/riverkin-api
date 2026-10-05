"""widen strava token columns to 255

Revision ID: 0015_strava_token_width
Revises: 0014_strava_accounts
Create Date: 2026-10-05 11:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015_strava_token_width"
down_revision: str | None = "0014_strava_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "strava_accounts", "access_token", type_=sa.String(length=255), existing_nullable=False
    )
    op.alter_column(
        "strava_accounts", "refresh_token", type_=sa.String(length=255), existing_nullable=False
    )


def downgrade() -> None:
    op.alter_column(
        "strava_accounts", "access_token", type_=sa.String(length=128), existing_nullable=False
    )
    op.alter_column(
        "strava_accounts", "refresh_token", type_=sa.String(length=128), existing_nullable=False
    )
