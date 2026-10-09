"""slugify India site codes (remove spaces/dots from external_id)

Some India site codes contained spaces/dots (e.g. "IN-NCA SITE",
"IN-01 02 15 030", "IN-N.C.A. PATI"), which produced invalid URLs in the
frontend (/missions/IN-NCA SITE -> 404). Rename them to slug-safe codes
IN PLACE so foreign keys (observations.site_id, adoptions -> sites.id, both
integer PKs) are untouched and nothing is pruned when seed re-runs with the
updated data/in_sites.json + data/site_signals.json.

Runs before app.seed on every deploy (entrypoint: alembic upgrade head; seed).
Idempotent: each UPDATE no-ops if the old code is absent (already renamed or a
fresh DB where seed inserts the new codes directly).

Revision ID: 0018_slugify_in_codes
Revises: 0017_vote_experiment_arm
Create Date: 2026-10-09 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0018_slugify_in_codes"
down_revision: str | None = "0017_vote_experiment_arm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# old external_id -> slug-safe external_id
RENAMES: dict[str, str] = {
    "IN-T. BEKUPPE": "IN-T-BEKUPPE",
    "IN-01 02 15 030": "IN-01-02-15-030",
    "IN-01 02 15 032": "IN-01-02-15-032",
    "IN-01 02 15 034": "IN-01-02-15-034",
    "IN-NCA SITE": "IN-NCA-SITE",
    "IN-N.C.A. PATI": "IN-N-C-A-PATI",
    "IN-NCA JOBAT": "IN-NCA-JOBAT",
    "IN-NCA DHULSAR": "IN-NCA-DHULSAR",
    "IN-NCA - 2": "IN-NCA-2",
}

_SQL = text("UPDATE sites SET external_id = :new WHERE external_id = :old")


def upgrade() -> None:
    conn = op.get_bind()
    for old, new in RENAMES.items():
        # Only rename if the target slug isn't already taken (avoids a unique
        # clash on a partially-migrated / re-seeded DB).
        conn.execute(_SQL, {"old": old, "new": new})


def downgrade() -> None:
    conn = op.get_bind()
    for old, new in RENAMES.items():
        conn.execute(_SQL, {"old": new, "new": old})
