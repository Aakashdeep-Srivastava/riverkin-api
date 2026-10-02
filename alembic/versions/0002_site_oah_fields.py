"""site OAH fields: waterbody, city, country, lat/lng, cadence, last_verified, rain, flag

Revision ID: 0002_site_oah_fields
Revises: 0001_initial
Create Date: 2026-10-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_site_oah_fields"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("waterbody", sa.String(length=255), nullable=True))
    op.add_column("sites", sa.Column("city", sa.String(length=128), nullable=True))
    op.add_column("sites", sa.Column("country", sa.String(length=128), nullable=True))
    op.add_column("sites", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("sites", sa.Column("lng", sa.Float(), nullable=True))
    op.add_column(
        "sites",
        sa.Column("cadence_days", sa.Integer(), nullable=False, server_default="14"),
    )
    op.add_column(
        "sites", sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sites",
        sa.Column("rain_48h_mm", sa.Float(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sites",
        sa.Column(
            "expert_flag_open", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_index("ix_sites_city", "sites", ["city"])


def downgrade() -> None:
    op.drop_index("ix_sites_city", table_name="sites")
    op.drop_column("sites", "expert_flag_open")
    op.drop_column("sites", "rain_48h_mm")
    op.drop_column("sites", "last_verified_at")
    op.drop_column("sites", "cadence_days")
    op.drop_column("sites", "lng")
    op.drop_column("sites", "lat")
    op.drop_column("sites", "country")
    op.drop_column("sites", "city")
    op.drop_column("sites", "waterbody")
