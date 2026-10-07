"""Concurrency-safe startup: migrate + seed under a Postgres advisory lock.

The container entrypoint runs this before uvicorn. Previously the Dockerfile ran
``alembic upgrade head && python -m app.seed`` inline, which was only safe at one
replica — on scale-out every new replica re-ran migrations + seed on boot, causing
brief cold-start errors (and, in the worst case, two replicas racing the same DDL).

Wrapping the whole migrate+seed in a session-level ``pg_advisory_lock`` serialises
it across replicas: the first replica to boot does the work while the others block
on the lock, then find migrations already at head (alembic no-op) and re-run the
idempotent seed. This achieves the "move seeding off per-replica boot for scaling"
goal without a separate init job or CI orchestration, and lets min-replicas safely
be > 1.

    python scripts/migrate_and_seed.py
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

from app.db import engine
from app.seed import seed, seed_challenges

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("app.migrate_and_seed")

# Arbitrary app-wide 64-bit key; any boot taking this key waits for the holder.
ADVISORY_LOCK_KEY = 7_270_914_001


async def main() -> None:
    # One dedicated connection holds the advisory lock for the whole critical
    # section. Other replicas calling pg_advisory_lock with the same key block
    # here until we release; normal queries are unaffected.
    async with engine.connect() as lock_conn:
        await lock_conn.exec_driver_sql(f"SELECT pg_advisory_lock({ADVISORY_LOCK_KEY})")
        logger.info("acquired startup advisory lock; migrating + seeding")
        try:
            result = subprocess.run(["alembic", "upgrade", "head"], check=False)
            if result.returncode != 0:
                logger.error("alembic upgrade failed (exit %s)", result.returncode)
                raise SystemExit(result.returncode)
            await seed()
            await seed_challenges()
            logger.info("migrate + seed complete")
        finally:
            await lock_conn.exec_driver_sql(
                f"SELECT pg_advisory_unlock({ADVISORY_LOCK_KEY})"
            )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except SystemExit:
        raise
    except Exception:
        logger.exception("startup migrate+seed failed")
        sys.exit(1)
