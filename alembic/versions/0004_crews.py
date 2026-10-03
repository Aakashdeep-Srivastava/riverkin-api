"""crews, crew_members, adoptions, checkins (later layer: L1/L2)

Revision ID: 0004_crews
Revises: 0003_verify_and_obs_fields
Create Date: 2026-10-03 03:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004_crews"
down_revision: str | None = "0003_verify_and_obs_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("is_minor_crew", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("streak_windows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("freezes_left", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    op.create_table(
        "crew_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crew_id", sa.Integer(), nullable=False),
        sa.Column("handle", sa.String(length=64), nullable=False),
        sa.Column("role_this_week", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_crew_members_crew_id", "crew_members", ["crew_id"])

    op.create_table(
        "adoptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crew_id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column(
            "adopted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_adoptions_crew_id", "adoptions", ["crew_id"])
    op.create_index("ix_adoptions_site_id", "adoptions", ["site_id"])

    op.create_table(
        "checkins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("crew_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crew_id"], ["crews.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_checkins_crew_id", "checkins", ["crew_id"])


def downgrade() -> None:
    op.drop_index("ix_checkins_crew_id", table_name="checkins")
    op.drop_table("checkins")
    op.drop_index("ix_adoptions_site_id", table_name="adoptions")
    op.drop_index("ix_adoptions_crew_id", table_name="adoptions")
    op.drop_table("adoptions")
    op.drop_index("ix_crew_members_crew_id", table_name="crew_members")
    op.drop_table("crew_members")
    op.drop_table("crews")
