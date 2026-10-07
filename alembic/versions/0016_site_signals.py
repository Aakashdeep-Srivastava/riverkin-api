"""site GBIF biodiversity + GloFAS discharge signal snapshots

Revision ID: 0016_site_signals
Revises: 0015_strava_token_width
Create Date: 2026-10-07 09:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0016_site_signals"
down_revision: str | None = "0015_strava_token_width"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sites",
        sa.Column("biodiversity", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "sites",
        sa.Column("discharge", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sites", "discharge")
    op.drop_column("sites", "biodiversity")
