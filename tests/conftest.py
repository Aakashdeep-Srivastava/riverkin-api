"""Shared test fixtures.

Each test runs against a clean slate: the mutable tables (observations, verify
items, votes) are truncated before every test so order-independent isolation
holds even though the whole suite shares one database. Seeded ``sites`` are left
in place (tests that need them call ``seed()`` themselves — it is idempotent).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.db import engine


@pytest.fixture(autouse=True)
async def clean_mutable_tables():
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE votes, verify_items, observations, "
                "checkins, adoptions, crew_members, crews, users RESTART IDENTITY CASCADE"
            )
        )
    yield
