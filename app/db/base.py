"""Async engine and session factory shared by entry points and tests."""

from __future__ import annotations

from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings
from app.db.models import Base


def build_engine(database_url: str | None = None) -> AsyncEngine:
    """Create an async engine for the given database URL.

    SQLite gets WAL mode and a busy timeout so the API and the background
    scheduler can share one file without ``database is locked`` errors.
    """
    url = database_url or get_settings().database_url
    engine = create_async_engine(url, pool_pre_ping=True)

    if engine.url.get_backend_name() == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def _configure_sqlite(dbapi_connection: object, _: object) -> None:
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
            finally:
                cursor.close()

    return engine


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create a session factory bound to the engine."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def ensure_schema(engine: AsyncEngine) -> None:
    """Create the schema for SQLite.

    PostgreSQL deployments keep using Alembic; the desktop build is a single
    local file and creates its tables on first launch.
    """
    if engine.url.get_backend_name() != "sqlite":
        return
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        # ``create_all`` never alters existing tables, so desktop databases
        # created by older releases need the few columns added since.
        await connection.run_sync(_add_missing_columns)


def _add_missing_columns(connection: Connection) -> None:
    """Forward-migrate a desktop SQLite file without a migration tool."""
    existing = {column["name"] for column in inspect(connection).get_columns("subscriptions")}
    if "deleted_at" not in existing:
        connection.execute(text("ALTER TABLE subscriptions ADD COLUMN deleted_at DATETIME"))
        # Rules removed by older releases were only deactivated.
        connection.execute(
            text("UPDATE subscriptions SET deleted_at = created_at WHERE is_active = 0")
        )
