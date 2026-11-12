"""Async engine and session factory shared by entry points and tests."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


def build_engine(database_url: str | None = None) -> AsyncEngine:
    """Create an async engine for the given database URL."""
    return create_async_engine(
        database_url or get_settings().database_url,
        pool_pre_ping=True,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the engine."""
    return async_sessionmaker(engine, expire_on_commit=False)
