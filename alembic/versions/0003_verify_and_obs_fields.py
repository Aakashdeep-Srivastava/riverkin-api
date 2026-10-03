"""observation answers/trust fields + verify_items + votes

Revision ID: 0003_verify_and_obs_fields
Revises: 0002_site_oah_fields
Create Date: 2026-10-03 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_verify_and_obs_fields"
down_revision: str | None = "0002_site_oah_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column(
            "answers",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="{}",
        ),
    )
    op.add_column("observations", sa.Column("feeling", sa.String(length=32), nullable=True))
    op.add_column(
        "observations",
        sa.Column("photo_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "observations",
        sa.Column("pipe_flag", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "observations",
        sa.Column("geom_ok", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "observations",
        sa.Column("quality", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column("observations", sa.Column("trust", sa.Float(), nullable=True))
    op.add_column("observations", sa.Column("gap_days_closed", sa.Integer(), nullable=True))
    op.add_column(
        "observations", sa.Column("fhir_bundle_id", sa.String(length=64), nullable=True)
    )

    op.create_table(
        "verify_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.Column("field_code", sa.String(length=64), nullable=False),
        sa.Column("question", sa.String(length=255), nullable=False),
        sa.Column("ai_box", sa.String(length=255), nullable=True),
        sa.Column("ai_agrees", sa.Boolean(), nullable=True),
        sa.Column("ai_confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_gold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gold_answer", sa.String(length=16), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["observation_id"], ["observations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_verify_items_observation_id", "verify_items", ["observation_id"])
    op.create_index("ix_verify_items_is_gold", "verify_items", ["is_gold"])
    op.create_index("ix_verify_items_resolved", "verify_items", ["resolved"])

    op.create_table(
        "votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("verify_item_id", sa.Integer(), nullable=False),
        sa.Column("voter_kind", sa.String(length=16), nullable=False, server_default="keeper"),
        sa.Column("voter_id", sa.String(length=64), nullable=True),
        sa.Column("answer", sa.String(length=16), nullable=False),
        sa.Column("ms_taken", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["verify_item_id"], ["verify_items.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_votes_verify_item_id", "votes", ["verify_item_id"])


def downgrade() -> None:
    op.drop_index("ix_votes_verify_item_id", table_name="votes")
    op.drop_table("votes")
    op.drop_index("ix_verify_items_resolved", table_name="verify_items")
    op.drop_index("ix_verify_items_is_gold", table_name="verify_items")
    op.drop_index("ix_verify_items_observation_id", table_name="verify_items")
    op.drop_table("verify_items")
    op.drop_column("observations", "fhir_bundle_id")
    op.drop_column("observations", "trust")
    op.drop_column("observations", "quality")
    op.drop_column("observations", "geom_ok")
    op.drop_column("observations", "pipe_flag")
    op.drop_column("observations", "photo_count")
    op.drop_column("observations", "feeling")
    op.drop_column("observations", "answers")
