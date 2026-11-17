import os
from collections.abc import AsyncIterator

import pytest
from app.db.base import build_engine, ensure_schema
from app.db.models import Base
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


@pytest.fixture
def database_url() -> str:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; integration tests require PostgreSQL")
    return url


@pytest.fixture
async def db_engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url, pool_pre_ping=True)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def session_factory(
    db_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def sqlite_engine(tmp_path: object) -> AsyncIterator[AsyncEngine]:
    """An isolated on-disk SQLite database for the desktop build."""
    path = tmp_path / "test.sqlite3"  # type: ignore[operator]
    engine = build_engine(f"sqlite+aiosqlite:///{path}")
    await ensure_schema(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def sqlite_session_factory(
    sqlite_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield async_sessionmaker(sqlite_engine, expire_on_commit=False)
