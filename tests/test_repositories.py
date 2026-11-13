from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.db.models import Offer, ParseRun, PriceSnapshot, Server
from app.db.repositories import (
    PARSE_RUN_ERROR,
    PARSE_RUN_OK,
    PARSE_RUN_RUNNING,
    SnapshotFilter,
    add_price_snapshots,
    count_active_subscriptions,
    current_price_summary,
    deactivate_subscription,
    fail_stale_parse_runs,
    finish_parse_run,
    get_category_by_path,
    get_or_create_category,
    get_or_create_user,
    get_user_subscription,
    latest_snapshot_point,
    list_active_categories,
    list_aggregated_snapshots,
    list_category_snapshot_filters,
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


async def test_filtered_offers_get_their_own_snapshots_and_summaries(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    offers = [
        parsed_offer(
            server_id=1,
            server_name="EU",
            price=Decimal("10"),
            item_type="предметы",
            title="Plush Nessie",
        ),
        parsed_offer(
            server_id=1,
            server_name="EU",
            price=Decimal("20"),
            item_type="предметы",
            title="Plush Nessie",
        ),
        parsed_offer(
            server_id=1,
            server_name="EU",
            price=Decimal("30"),
            item_type="услуги",
            title="Plush Nessie boost",
        ),
        parsed_offer(
            server_id=2,
            server_name="NA",
            price=Decimal("40"),
            item_type="предметы",
            title="Plush Nessie",
        ),
        parsed_offer(
            server_id=2,
            server_name="NA",
            price=Decimal("50"),
            item_type="услуги",
            title="Other",
        ),
    ]

    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        servers = await upsert_servers(session, category.id, offers)
        eu_id = servers[1].id
        na_id = servers[2].id
        await replace_offers(session, category.id, offers, servers)
        snapshots = await add_price_snapshots(
            session,
            category.id,
            offers,
            servers,
            [
                SnapshotFilter(
                    server_id=eu_id,
                    item_type="предметы",
                    query="plush nessie",
                ),
                SnapshotFilter(server_id=None, item_type="услуги"),
            ],
        )
        await session.commit()
        category_id = category.id

    # Two baseline rows plus three rows for the requested slices.
    assert len(snapshots) == 5

    async with session_factory() as session:
        baseline_eu = await list_price_snapshots(session, category_id, server_id=eu_id)
        filtered_eu = await list_price_snapshots(
            session,
            category_id,
            server_id=eu_id,
            item_type="предметы",
            query="plush nessie",
        )
        services_eu = await list_price_snapshots(
            session, category_id, server_id=eu_id, item_type="услуги"
        )
        services_na = await list_price_snapshots(
            session, category_id, server_id=na_id, item_type="услуги"
        )
        filtered_point = await latest_snapshot_point(
            session,
            category_id,
            eu_id,
            item_type="предметы",
            query="plush nessie",
        )
        services_point = await latest_snapshot_point(session, category_id, item_type="услуги")
        filtered_summary = await current_price_summary(
            session,
            category_id,
            item_type="предметы",
            query="plush nessie",
        )
        filtered_eu_summary = await current_price_summary(
            session,
            category_id,
            eu_id,
            item_type="предметы",
        )
        services_summary = await current_price_summary(session, category_id, item_type="услуги")
        services_query_summary = await current_price_summary(
            session,
            category_id,
            item_type="услуги",
            query="nessie",
        )
        aggregates = await list_aggregated_snapshots(session, category_id, item_type="услуги")

    assert len(baseline_eu) == 1
    assert baseline_eu[0].item_type is None
    assert baseline_eu[0].min_price == Decimal("10")
    assert baseline_eu[0].offer_count == 3

    assert len(filtered_eu) == 1
    assert filtered_eu[0].item_type == "предметы"
    assert filtered_eu[0].query == "plush nessie"
    assert filtered_eu[0].min_price == Decimal("10")
    assert filtered_eu[0].median_price == Decimal("15")
    assert filtered_eu[0].offer_count == 2

    assert [row.min_price for row in services_eu] == [Decimal("30")]
    assert [row.min_price for row in services_na] == [Decimal("50")]

    assert filtered_point is not None
    assert filtered_point.min_price == Decimal("10")
    assert filtered_point.median_price == Decimal("15")
    assert filtered_point.offer_count == 2

    assert services_point is not None
    assert services_point.min_price == Decimal("30")
    assert services_point.median_price == Decimal("40")
    assert services_point.offer_count == 2

    assert filtered_summary is not None
    assert filtered_summary.min_price == Decimal("10")
    assert filtered_summary.median_price == Decimal("20")
    assert filtered_summary.offer_count == 3

    assert filtered_eu_summary is not None
    assert filtered_eu_summary.min_price == Decimal("10")
    assert filtered_eu_summary.median_price == Decimal("15")
    assert filtered_eu_summary.offer_count == 2

    assert services_summary is not None
    assert services_summary.min_price == Decimal("30")
    assert services_summary.median_price == Decimal("40")
    assert services_summary.offer_count == 2

    assert services_query_summary is not None
    assert services_query_summary.offer_count == 1
    assert services_query_summary.min_price == Decimal("30")

    assert len(aggregates) == 1
    assert aggregates[0].min_price == Decimal("30")
    assert aggregates[0].median_price == Decimal("40")
    assert aggregates[0].offer_count == 2


async def test_subscription_identity_includes_offer_filter(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, 7001)
        category = await get_or_create_category(session, INFO)
        servers = await upsert_servers(
            session,
            category.id,
            [parsed_offer(server_id=1, server_name="EU")],
        )
        baseline = await upsert_subscription(
            session,
            user_id=user.id,
            category_id=category.id,
            server_id=servers[1].id,
            mode="abs",
            threshold=Decimal("100"),
        )
        filtered = await upsert_subscription(
            session,
            user_id=user.id,
            category_id=category.id,
            server_id=servers[1].id,
            mode="abs",
            threshold=Decimal("100"),
            item_type="предметы",
            query="plush nessie",
        )
        await session.commit()
        user_id = user.id
        category_id = category.id
        server_id = servers[1].id
        baseline_id = baseline.id
        filtered_id = filtered.id

    assert filtered_id != baseline_id

    async with session_factory() as session:
        same = await upsert_subscription(
            session,
            user_id=user_id,
            category_id=category_id,
            server_id=server_id,
            mode="abs",
            threshold=Decimal("80"),
            item_type="предметы",
            query="plush nessie",
        )
        await session.commit()

        assert same.id == filtered_id
        assert same.threshold == Decimal("80")

        filters = await list_category_snapshot_filters(session, category_id)

    assert {(item.server_id, item.item_type, item.query) for item in filters} == {
        (server_id, None, None),
        (server_id, "предметы", "plush nessie"),
    }


async def test_fail_stale_parse_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        stale = await start_parse_run(session, category.id)
        stale.started_at = now - timedelta(hours=3)
        fresh = await start_parse_run(session, category.id)
        fresh.started_at = now - timedelta(minutes=5)
        await session.commit()
        stale_id = stale.id
        fresh_id = fresh.id

    async with session_factory() as session:
        count = await fail_stale_parse_runs(
            session,
            older_than=now - timedelta(hours=1),
        )
        await session.commit()

    async with session_factory() as session:
        stale_row = await session.get(ParseRun, stale_id)
        fresh_row = await session.get(ParseRun, fresh_id)

    assert count == 1
    assert stale_row is not None
    assert stale_row.status == PARSE_RUN_ERROR
    assert stale_row.finished_at is not None
    assert stale_row.error_text == "interrupted by worker restart"
    assert fresh_row is not None
    assert fresh_row.status == PARSE_RUN_RUNNING
