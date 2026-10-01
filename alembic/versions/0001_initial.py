"""initial schema: postgis extension + sites + observations

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-02 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostGIS must exist before any geometry column is created.
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis;")

    op.create_table(
        "sites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_id", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "location",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, spatial_index=False
            ),
            nullable=True,
        ),
        sa.Column("need_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "simulated", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_sites_external_id", "sites", ["external_id"], unique=True)
    # Explicit spatial (GIST) index on the geometry column.
    op.execute("CREATE INDEX ix_sites_location ON sites USING gist (location);")

    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("site_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="submitted",
        ),
        sa.Column("photo_path", sa.String(length=512), nullable=True),
        sa.Column("photo_phash", sa.String(length=64), nullable=True),
        sa.Column("reliability_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["sites.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_observations_site_id", "observations", ["site_id"])
    op.create_index("ix_observations_status", "observations", ["status"])


def downgrade() -> None:
    op.drop_index("ix_observations_status", table_name="observations")
    op.drop_index("ix_observations_site_id", table_name="observations")
    op.drop_table("observations")
    op.execute("DROP INDEX IF EXISTS ix_sites_location;")
    op.drop_index("ix_sites_external_id", table_name="sites")
    op.drop_table("sites")
