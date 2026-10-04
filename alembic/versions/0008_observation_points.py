"""observation points (River Value reward captured at submit)

Revision ID: 0008_observation_points
Revises: 0007_site_oah_baseline
Create Date: 2026-10-04 15:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_observation_points"
down_revision: str | None = "0007_site_oah_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("points", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("observations", "points")
