"""community_posts — the shared community feed

Revision ID: 0019_community_posts
Revises: 0018_slugify_in_codes
Create Date: 2026-10-12 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019_community_posts"
down_revision: str | None = "0018_slugify_in_codes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "community_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("author_key", sa.String(length=64), nullable=False),
        sa.Column("author_name", sa.String(length=80), nullable=False, server_default="Guest"),
        sa.Column("body", sa.String(length=300), nullable=False),
        sa.Column(
            "site_id",
            sa.Integer(),
            sa.ForeignKey("sites.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_community_posts_author_key", "community_posts", ["author_key"])
    op.create_index("ix_community_posts_created_at", "community_posts", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_community_posts_created_at", table_name="community_posts")
    op.drop_index("ix_community_posts_author_key", table_name="community_posts")
    op.drop_table("community_posts")
