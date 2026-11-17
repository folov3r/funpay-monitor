"""Repository behaviour on the SQLite backend used by the desktop build."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import Category, PriceSnapshot, Server
from app.db.repositories import (
    SnapshotFilter,
    add_price_snapshots,
    historical_min_price,
    latest_category_captured_at,
    latest_snapshot_point,
    list_aggregated_snapshots,
    list_price_snapshots,
    previous_snapshot_point,
)
from app.parsers.base import Offer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _offer(server_id: int, price: str, *, title: str | None = None) -> Offer:
    return Offer(
        seller_id=1,
        seller_name="seller",
        amount=None,
        price=Decimal(price),
        currency="RUB",
        server_id=server_id,
        server_name=f"S{server_id}",
        title=title,
    )


async def _category_with_servers(
    session: AsyncSession,
) -> tuple[Category, dict[int, Server]]:
    category = Category(funpay_id=1, type="chip", title="A", url_path="/chips/1/")
    session.add(category)
    await session.flush()
    servers = {
        funpay_id: Server(category_id=category.id, funpay_server_id=funpay_id, name=f"S{funpay_id}")
        for funpay_id in (1, 2)
    }
    session.add_all(servers.values())
    await session.flush()
    return category, servers


async def test_add_price_snapshots_uses_one_timestamp_per_run(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sqlite_session_factory() as session:
        category, servers = await _category_with_servers(session)
        snapshots = await add_price_snapshots(
            session,
            category.id,
            [_offer(1, "10"), _offer(2, "20")],
            servers,
        )
        await session.commit()
        timestamps = {snapshot.captured_at for snapshot in snapshots}

    assert len(snapshots) == 2
    assert len(timestamps) == 1


async def test_aggregated_snapshots_keep_decimal_prices(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sqlite_session_factory() as session:
        category, servers = await _category_with_servers(session)
        await add_price_snapshots(
            session,
            category.id,
            [_offer(1, "1.000001"), _offer(2, "3.000003")],
            servers,
        )
        await session.commit()
        category_id = category.id

    async with sqlite_session_factory() as session:
        aggregates = await list_aggregated_snapshots(session, category_id)

    assert len(aggregates) == 1
    point = aggregates[0]
    assert point.min_price == Decimal("1.000001")
    assert point.median_price == Decimal("2.000002")
    assert point.offer_count == 2


async def test_history_points_aggregate_across_servers(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sqlite_session_factory() as session:
        category, servers = await _category_with_servers(session)
        await add_price_snapshots(
            session,
            category.id,
            [_offer(1, "10"), _offer(2, "30")],
            servers,
        )
        await session.commit()
        first_at = await latest_category_captured_at(session, category.id)
        await add_price_snapshots(
            session,
            category.id,
            [_offer(1, "5"), _offer(2, "7")],
            servers,
        )
        await session.commit()
        category_id = category.id
        latest_at = await latest_category_captured_at(session, category_id)

    assert first_at is not None
    assert latest_at is not None
    assert latest_at > first_at
    async with sqlite_session_factory() as session:
        latest = await latest_snapshot_point(session, category_id)
        previous = await previous_snapshot_point(session, category_id, None, latest_at)
        historical = await historical_min_price(session, category_id, None, latest_at)

    assert latest is not None
    assert latest.min_price == Decimal("5")
    assert latest.median_price == Decimal("6")
    assert previous is not None
    assert previous.min_price == Decimal("10")
    assert previous.median_price == Decimal("20")
    assert historical == Decimal("10")


async def test_filtered_snapshots_have_their_own_history(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sqlite_session_factory() as session:
        category, servers = await _category_with_servers(session)
        await add_price_snapshots(
            session,
            category.id,
            [
                _offer(1, "10", title="Cosmic Relic"),
                _offer(1, "50", title="Other"),
                _offer(2, "20", title="Cosmic Relic"),
            ],
            servers,
            filters=[SnapshotFilter(server_id=servers[1].id, query="cosmic")],
        )
        await session.commit()
        category_id = category.id
        server_id = servers[1].id

    async with sqlite_session_factory() as session:
        filtered = await list_price_snapshots(
            session,
            category_id,
            server_id=server_id,
            query="cosmic",
        )
        unfiltered = await list_price_snapshots(session, category_id, server_id=server_id)

    assert [(row.min_price, row.offer_count) for row in filtered] == [(Decimal("10"), 1)]
    assert [(row.min_price, row.offer_count) for row in unfiltered] == [(Decimal("10"), 2)]


async def test_snapshot_timestamps_are_aware_utc(
    sqlite_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with sqlite_session_factory() as session:
        category, servers = await _category_with_servers(session)
        await add_price_snapshots(session, category.id, [_offer(1, "10")], servers)
        await session.commit()

    async with sqlite_session_factory() as session:
        row = (await session.scalars(select(PriceSnapshot))).one()

    assert row.captured_at.tzinfo is not None
    assert row.captured_at.utcoffset() == timedelta(0)
    assert row.captured_at <= datetime.now(UTC)
