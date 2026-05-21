from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nexusflow.shared.config.settings import get_settings
from nexusflow.shared.models.db import Base

logger = logging.getLogger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_db() -> None:
    """Initialize the database engine and verify connectivity. Call at startup."""
    global _engine, _session_factory

    settings = get_settings()
    _engine = create_async_engine(
        settings.database.dsn,
        pool_size=settings.database.pool_size,
        max_overflow=settings.database.max_overflow,
        pool_timeout=settings.database.pool_timeout,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=False,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    async with _engine.connect() as conn:
        await conn.run_sync(lambda _: None)
    logger.info("Database connection pool initialized: %s", settings.database.host)


async def close_db() -> None:
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None
        logger.info("Database connection pool closed")


@asynccontextmanager
async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield an async database session within a transaction."""
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with _session_factory() as session:
        async with session.begin():
            try:
                yield session
            except Exception:
                await session.rollback()
                raise


async def create_all_tables() -> None:
    """Dev-only: create all tables directly without Alembic. Do not use in production."""
    if _engine is None:
        raise RuntimeError("Database not initialized.")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.warning("Tables created via create_all (dev mode only)")
