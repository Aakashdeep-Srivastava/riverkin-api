"""observation photos list (collective multi-image scoring)

Revision ID: 0010_observation_photos
Revises: 0009_observation_user
Create Date: 2026-10-04 16:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010_observation_photos"
down_revision: str | None = "0009_observation_user"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("photos", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("observations", "photos")
