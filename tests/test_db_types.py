"""SQLite compatibility tests for the cross-database column types."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

from app.db.models import Category, Offer, Server
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_ensure_schema_creates_all_tables(sqlite_engine: object) -> None:
    async with sqlite_engine.connect() as connection:  # type: ignore[attr-defined]
        rows = await connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        )
    names = {row[0] for row in rows}
    assert {
        "users",
        "categories",
        "servers",
        "offers",
        "price_snapshots",
        "parse_runs",
        "subscriptions",
        "notifications",
    } <= names


async def test_bigint_primary_key_autoincrements(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sqlite_session_factory() as session:
        first = Category(funpay_id=1, type="chip", title="A", url_path="/chips/1/")
        second = Category(funpay_id=2, type="chip", title="B", url_path="/chips/2/")
        session.add_all([first, second])
        await session.commit()
        assert first.id is not None
        assert second.id is not None
        assert second.id > first.id


async def test_utc_datetime_roundtrip_returns_aware_utc(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    aware = datetime(2026, 11, 17, 12, 30, 45, tzinfo=timezone(timedelta(hours=3)))
    naive = datetime(2026, 11, 17, 9, 30, 45)

    async with sqlite_session_factory() as session:
        session.add_all(
            [
                Category(
                    funpay_id=1,
                    type="chip",
                    title="Aware",
                    url_path="/chips/1/",
                    last_parsed_at=aware,
                ),
                Category(
                    funpay_id=2,
                    type="chip",
                    title="Naive",
                    url_path="/chips/2/",
                    last_parsed_at=naive,
                ),
            ]
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        rows = (await session.scalars(select(Category).order_by(Category.id))).all()

    expected = datetime(2026, 11, 17, 9, 30, 45, tzinfo=UTC)
    assert rows[0].last_parsed_at == expected
    assert rows[1].last_parsed_at == expected
    assert rows[0].last_parsed_at.tzinfo is not None


async def test_money_keeps_six_decimals(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    price = Decimal("0.000123")
    amount = Decimal("1500.25")

    async with sqlite_session_factory() as session:
        category = Category(funpay_id=1, type="chip", title="A", url_path="/chips/1/")
        session.add(category)
        await session.flush()
        server = Server(category_id=category.id, funpay_server_id=1, name="S1")
        session.add(server)
        await session.flush()
        session.add(
            Offer(
                category_id=category.id,
                server_id=server.id,
                price=price,
                amount=amount,
            )
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        offer = (await session.scalars(select(Offer))).one()
        raw_price = await session.scalar(text("SELECT price FROM offers"))

    assert offer.price == price
    assert offer.amount == amount
    # Money is stored as integer micro-units, not as a float.
    assert raw_price == 123


async def test_money_rounds_half_up(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sqlite_session_factory() as session:
        category = Category(funpay_id=1, type="chip", title="A", url_path="/chips/1/")
        session.add(category)
        await session.flush()
        server = Server(category_id=category.id, funpay_server_id=1, name="S1")
        session.add(server)
        await session.flush()
        session.add(
            Offer(
                category_id=category.id,
                server_id=server.id,
                price=Decimal("1.0000005"),
                amount=Decimal("2.005"),
            )
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        offer = (await session.scalars(select(Offer))).one()

    assert offer.price == Decimal("1.000001")
    assert offer.amount == Decimal("2.01")


async def test_null_money_and_timestamps_roundtrip(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sqlite_session_factory() as session:
        category = Category(funpay_id=1, type="chip", title="A", url_path="/chips/1/")
        session.add(category)
        await session.flush()
        server = Server(category_id=category.id, funpay_server_id=1, name="S1")
        session.add(server)
        await session.flush()
        session.add(
            Offer(
                category_id=category.id,
                server_id=server.id,
                price=Decimal("10"),
                amount=None,
            )
        )
        await session.commit()

    async with sqlite_session_factory() as session:
        offer = (await session.scalars(select(Offer))).one()
        category = (await session.scalars(select(Category))).one()

    assert offer.amount is None
    assert category.last_parsed_at is None
