"""observation author link (permanent per-user River Score)

Revision ID: 0009_observation_user
Revises: 0008_observation_points
Create Date: 2026-10-04 15:45:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009_observation_user"
down_revision: str | None = "0008_observation_points"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("observations", sa.Column("user_id", sa.Integer(), nullable=True))
    op.create_index("ix_observations_user_id", "observations", ["user_id"])
    op.create_foreign_key(
        "fk_observations_user_id",
        "observations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_observations_user_id", "observations", type_="foreignkey")
    op.drop_index("ix_observations_user_id", table_name="observations")
    op.drop_column("observations", "user_id")
