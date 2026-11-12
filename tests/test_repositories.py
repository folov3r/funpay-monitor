from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import Offer, ParseRun, PriceSnapshot, Server
from app.db.repositories import (
    PARSE_RUN_OK,
    PARSE_RUN_RUNNING,
    add_price_snapshots,
    count_active_subscriptions,
    current_price_summary,
    deactivate_subscription,
    finish_parse_run,
    get_category_by_path,
    get_or_create_category,
    get_or_create_user,
    get_user_subscription,
    list_active_categories,
    list_aggregated_snapshots,
    list_price_snapshots,
    list_user_subscriptions,
    replace_offers,
    start_parse_run,
    upsert_servers,
    upsert_subscription,
)
from app.parsers.base import CategoryInfo
from app.parsers.base import Offer as ParsedOffer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INFO = CategoryInfo(
    funpay_id=30,
    type="chip",
    title="Серебро Albion Online",
    url_path="/chips/30/",
)


def parsed_offer(**overrides: object) -> ParsedOffer:
    defaults: dict[str, object] = {
        "seller_id": 1,
        "seller_name": "seller",
        "amount": Decimal("10"),
        "price": Decimal("100"),
        "currency": "RUB",
        "server_id": 1,
        "server_name": "EU",
        "is_online": True,
        "is_promo": False,
    }
    defaults.update(overrides)
    return ParsedOffer(**defaults)  # type: ignore[arg-type]


async def test_get_or_create_category_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        await session.commit()
        category_id = category.id

    updated = replace(INFO, title="Серебро Albion Online (new)")
    async with session_factory() as session:
        same = await get_or_create_category(session, updated)
        await session.commit()

    assert same.id == category_id
    assert same.title == "Серебро Albion Online (new)"

    async with session_factory() as session:
        by_path = await get_category_by_path(session, "/chips/30/")
        active = await list_active_categories(session)

    assert by_path is not None
    assert by_path.id == category_id
    assert [category.id for category in active] == [category_id]


async def test_server_upsert_and_offer_replacement(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    offers = [
        parsed_offer(server_id=1, server_name="EU", price=Decimal("10")),
        parsed_offer(server_id=1, server_name="EU", price=Decimal("20")),
        parsed_offer(server_id=2, server_name="NA", price=Decimal("30")),
    ]

    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        servers = await upsert_servers(session, category.id, offers)
        assert set(servers) == {1, 2}
        assert servers[1].id is not None

        count = await replace_offers(session, category.id, offers, servers)
        assert count == 3
        await session.commit()
        category_id = category.id

    async with session_factory() as session:
        rows = list(await session.scalars(select(Offer).where(Offer.category_id == category_id)))
        assert len(rows) == 3
        assert {row.price for row in rows} == {Decimal("10"), Decimal("20"), Decimal("30")}

        servers = await upsert_servers(session, category_id, offers)
        count = await replace_offers(session, category_id, offers[:1], servers)
        assert count == 1
        await session.commit()

    async with session_factory() as session:
        rows = list(await session.scalars(select(Offer).where(Offer.category_id == category_id)))
        assert len(rows) == 1
        assert rows[0].price == Decimal("10")


async def test_snapshots_are_grouped_by_server(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    offers = [
        parsed_offer(server_id=1, server_name="EU", price=Decimal("10")),
        parsed_offer(server_id=1, server_name="EU", price=Decimal("20")),
        parsed_offer(server_id=2, server_name="NA", price=Decimal("30")),
    ]

    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        servers = await upsert_servers(session, category.id, offers)
        eu_server_id = servers[1].id
        na_server_id = servers[2].id
        snapshots = await add_price_snapshots(session, category.id, offers, servers)
        await session.commit()
        category_id = category.id

    assert len(snapshots) == 2

    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(PriceSnapshot).where(PriceSnapshot.category_id == category_id)
            )
        )
        by_server = {row.server_id: row for row in rows}

    assert by_server[eu_server_id].min_price == Decimal("10")
    assert by_server[eu_server_id].median_price == Decimal("15")
    assert by_server[eu_server_id].offer_count == 2
    assert by_server[na_server_id].min_price == Decimal("30")
    assert by_server[na_server_id].median_price == Decimal("30")
    assert by_server[na_server_id].offer_count == 1


async def test_parse_run_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        run = await start_parse_run(session, category.id)
        await session.commit()
        run_id = run.id
        assert run.status == PARSE_RUN_RUNNING

    async with session_factory() as session:
        run = await session.get(ParseRun, run_id)
        assert run is not None
        await finish_parse_run(session, run, status=PARSE_RUN_OK, offers_found=42, error_text=None)
        await session.commit()

    async with session_factory() as session:
        run = await session.get(ParseRun, run_id)
        assert run is not None
        assert run.status == PARSE_RUN_OK
        assert run.offers_found == 42
        assert run.finished_at is not None
        assert run.error_text is None


async def test_servers_are_reused_between_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        first = await upsert_servers(
            session, category.id, [parsed_offer(server_id=1, server_name="EU")]
        )
        await session.commit()
        first_id = first[1].id

    async with session_factory() as session:
        second = await upsert_servers(
            session, category.id, [parsed_offer(server_id=1, server_name="Europe")]
        )
        await session.commit()

    assert second[1].id == first_id
    assert second[1].name == "Europe"

    async with session_factory() as session:
        rows = list(await session.scalars(select(Server)))
    assert len(rows) == 1


async def test_list_price_snapshots_filters_and_orders(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)

    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        servers = await upsert_servers(
            session,
            category.id,
            [
                parsed_offer(server_id=1, server_name="EU"),
                parsed_offer(server_id=2, server_name="NA"),
            ],
        )
        eu_id = servers[1].id
        na_id = servers[2].id
        session.add_all(
            [
                PriceSnapshot(
                    category_id=category.id,
                    server_id=eu_id,
                    min_price=Decimal("10"),
                    median_price=Decimal("11"),
                    offer_count=1,
                    captured_at=start + timedelta(days=1),
                ),
                PriceSnapshot(
                    category_id=category.id,
                    server_id=na_id,
                    min_price=Decimal("20"),
                    median_price=Decimal("21"),
                    offer_count=1,
                    captured_at=start + timedelta(days=2),
                ),
                PriceSnapshot(
                    category_id=category.id,
                    server_id=eu_id,
                    min_price=Decimal("12"),
                    median_price=Decimal("13"),
                    offer_count=1,
                    captured_at=start + timedelta(days=3),
                ),
            ]
        )
        await session.commit()
        category_id = category.id

    async with session_factory() as session:
        all_rows = await list_price_snapshots(session, category_id)
        eu_rows = await list_price_snapshots(session, category_id, server_id=eu_id)
        since_rows = await list_price_snapshots(
            session, category_id, since=start + timedelta(days=2)
        )
        limited_rows = await list_price_snapshots(session, category_id, limit=2)

    assert [row.captured_at for row in all_rows] == [
        start + timedelta(days=1),
        start + timedelta(days=2),
        start + timedelta(days=3),
    ]
    assert [row.min_price for row in eu_rows] == [Decimal("10"), Decimal("12")]
    assert [row.captured_at for row in since_rows] == [
        start + timedelta(days=2),
        start + timedelta(days=3),
    ]
    assert [row.captured_at for row in limited_rows] == [
        start + timedelta(days=2),
        start + timedelta(days=3),
    ]


async def test_user_upsert_reuses_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, 1001)
        await session.commit()
        user_id = user.id

    async with session_factory() as session:
        same = await get_or_create_user(session, 1001, first_name="Konstantin")
        await session.commit()

    assert same.id == user_id
    assert same.first_name == "Konstantin"


async def test_subscription_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, 2001)
        category = await get_or_create_category(session, INFO)
        servers = await upsert_servers(
            session,
            category.id,
            [parsed_offer(server_id=1, server_name="EU")],
        )
        subscription = await upsert_subscription(
            session,
            user_id=user.id,
            category_id=category.id,
            server_id=servers[1].id,
            mode="abs",
            threshold=Decimal("100"),
        )
        await session.commit()
        user_id = user.id
        category_id = category.id
        server_id = servers[1].id
        subscription_id = subscription.id

    async with session_factory() as session:
        subscriptions = await list_user_subscriptions(session, user_id)
        fetched = await get_user_subscription(session, subscription_id, user_id)
        count = await count_active_subscriptions(session, user_id)

    assert len(subscriptions) == 1
    assert subscriptions[0].category.title == "Серебро Albion Online"
    assert subscriptions[0].server is not None
    assert subscriptions[0].server.name == "EU"
    assert fetched is not None
    assert fetched.id == subscription_id
    assert count == 1

    async with session_factory() as session:
        updated = await upsert_subscription(
            session,
            user_id=user_id,
            category_id=category_id,
            server_id=server_id,
            mode="abs",
            threshold=Decimal("80"),
        )
        await session.commit()
        assert updated.id == subscription_id
        assert updated.threshold == Decimal("80")

    async with session_factory() as session:
        removed = await deactivate_subscription(session, subscription_id, user_id)
        await session.commit()
        assert removed is not None

    async with session_factory() as session:
        subscriptions = await list_user_subscriptions(session, user_id)
        count = await count_active_subscriptions(session, user_id)
        duplicate = await upsert_subscription(
            session,
            user_id=user_id,
            category_id=category_id,
            server_id=server_id,
            mode="abs",
            threshold=Decimal("90"),
        )
        await session.commit()

    assert subscriptions == []
    assert count == 0
    assert duplicate.id != subscription_id


async def test_current_price_summary_and_aggregation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    offers = [
        parsed_offer(server_id=1, server_name="EU", price=Decimal("10")),
        parsed_offer(server_id=1, server_name="EU", price=Decimal("20")),
        parsed_offer(server_id=2, server_name="NA", price=Decimal("30")),
    ]

    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        servers = await upsert_servers(session, category.id, offers)
        await replace_offers(session, category.id, offers, servers)
        await add_price_snapshots(session, category.id, offers, servers)
        await session.commit()
        category_id = category.id
        eu_id = servers[1].id

    async with session_factory() as session:
        everything = await current_price_summary(session, category_id)
        europe = await current_price_summary(session, category_id, eu_id)
        missing = await current_price_summary(session, category_id, 999999)
        aggregates = await list_aggregated_snapshots(session, category_id)

    assert everything is not None
    assert everything.min_price == Decimal("10")
    assert everything.median_price == Decimal("20")
    assert everything.offer_count == 3
    assert europe is not None
    assert europe.min_price == Decimal("10")
    assert europe.median_price == Decimal("15")
    assert europe.offer_count == 2
    assert missing is None

    assert len(aggregates) == 1
    assert aggregates[0].min_price == Decimal("10")
    assert aggregates[0].median_price == Decimal("22.5")
    assert aggregates[0].offer_count == 3
