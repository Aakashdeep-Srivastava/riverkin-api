"""Async SQLAlchemy engine, session factory, declarative Base and FastAPI dependency."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# Creating the engine does NOT open a connection, so importing this module is
# cheap and safe in tests that never touch the database (e.g. /healthz).
#
# Under pytest, each test runs on its own event loop; a pooled asyncpg
# connection opened on one loop cannot be reused on the next ("attached to a
# different loop"). NullPool opens/closes a fresh connection per use, which is
# correct for tests and fine for our single-replica API.
_engine_kwargs: dict = {"future": True}
if settings.APP_ENV == "test":
    _engine_kwargs["poolclass"] = NullPool
else:
    _engine_kwargs["pool_pre_ping"] = True

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async DB session."""
    async with SessionLocal() as session:
        yield session
