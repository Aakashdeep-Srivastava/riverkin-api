"""vote experiment arm (AI-assist verification lift A/B)

Revision ID: 0017_vote_experiment_arm
Revises: 0016_site_signals
Create Date: 2026-10-07 10:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017_vote_experiment_arm"
down_revision: str | None = "0016_site_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable: votes cast before the experiment carry no arm and are ignored by
    # the lift metric.
    op.add_column("votes", sa.Column("arm", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("votes", "arm")
