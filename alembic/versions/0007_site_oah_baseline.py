"""site altitude + real OAH baseline (ecology + health_risk snapshots)

Revision ID: 0007_site_oah_baseline
Revises: 0006_photo_analysis
Create Date: 2026-10-04 11:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007_site_oah_baseline"
down_revision: str | None = "0006_photo_analysis"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("altitude_m", sa.Float(), nullable=True))
    op.add_column(
        "sites",
        sa.Column("ecology", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "sites",
        sa.Column("health_risk", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "health_risk")
    op.drop_column("sites", "ecology")
    op.drop_column("sites", "altitude_m")
