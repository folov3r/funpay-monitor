"""Database access helpers used by the worker and bot."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from statistics import median

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Category,
    Offer,
    ParseRun,
    PriceSnapshot,
    Server,
    Subscription,
    User,
)
from app.parsers.base import CategoryInfo
from app.parsers.base import Offer as ParsedOffer

PARSE_RUN_RUNNING = "running"
PARSE_RUN_OK = "ok"
PARSE_RUN_ERROR = "error"
PARSE_RUN_PARTIAL = "partial"


@dataclass(frozen=True, slots=True)
class PriceSummary:
    """Current price statistics for a category or one of its servers."""

    min_price: Decimal
    median_price: Decimal
    offer_count: int


@dataclass(frozen=True, slots=True)
class SnapshotAggregate:
    """Category-wide snapshot aggregated across all servers from one parse run."""

    captured_at: datetime
    min_price: Decimal
    median_price: Decimal
    offer_count: int


async def get_or_create_category(session: AsyncSession, info: CategoryInfo) -> Category:
    """Find a category by its FunPay identity or create it, refreshing metadata."""
    category = await session.scalar(
        select(Category).where(
            Category.funpay_id == info.funpay_id,
            Category.type == info.type,
        )
    )
    if category is None:
        category = Category(
            funpay_id=info.funpay_id,
            type=info.type,
            title=info.title,
            game_title=info.game_title,
            url_path=info.url_path,
            is_active=True,
        )
        session.add(category)
        await session.flush()
        return category

    category.title = info.title
    category.url_path = info.url_path
    if info.game_title:
        category.game_title = info.game_title
    return category


async def get_category_by_path(session: AsyncSession, url_path: str) -> Category | None:
    """Find a tracked category by its FunPay path."""
    return await session.scalar(select(Category).where(Category.url_path == url_path))


async def list_active_categories(session: AsyncSession) -> list[Category]:
    """Return all categories the scheduler should parse."""
    result = await session.scalars(
        select(Category).where(Category.is_active.is_(True)).order_by(Category.id)
    )
    return list(result)


async def upsert_servers(
    session: AsyncSession,
    category_id: int,
    offers: list[ParsedOffer],
) -> dict[int, Server]:
    """Create missing servers and return a map of FunPay server id to ORM row."""
    wanted = {offer.server_id: offer.server_name for offer in offers}
    existing = await session.scalars(select(Server).where(Server.category_id == category_id))
    servers = {server.funpay_server_id: server for server in existing}

    for funpay_server_id, name in wanted.items():
        server = servers.get(funpay_server_id)
        if server is None:
            server = Server(
                category_id=category_id,
                funpay_server_id=funpay_server_id,
                name=name,
            )
            session.add(server)
            servers[funpay_server_id] = server
        elif name and server.name != name:
            server.name = name

    await session.flush()
    return servers


async def replace_offers(
    session: AsyncSession,
    category_id: int,
    offers: list[ParsedOffer],
    servers: dict[int, Server],
) -> int:
    """Replace the current offer table of a category with a fresh parse result."""
    await session.execute(delete(Offer).where(Offer.category_id == category_id))

    rows = [
        Offer(
            category_id=category_id,
            server_id=servers[offer.server_id].id,
            seller_id=offer.seller_id,
            seller_name=offer.seller_name,
            amount=offer.amount,
            price=offer.price,
            currency=offer.currency,
            is_online=offer.is_online,
            is_promo=offer.is_promo,
        )
        for offer in offers
    ]
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def add_price_snapshots(
    session: AsyncSession,
    category_id: int,
    offers: list[ParsedOffer],
    servers: dict[int, Server],
) -> list[PriceSnapshot]:
    """Write one min/median/count snapshot per server that has offers."""
    prices_by_server: dict[int, list[Decimal]] = defaultdict(list)
    for offer in offers:
        prices_by_server[offer.server_id].append(offer.price)

    snapshots: list[PriceSnapshot] = []
    for funpay_server_id, prices in prices_by_server.items():
        snapshot = PriceSnapshot(
            category_id=category_id,
            server_id=servers[funpay_server_id].id,
            min_price=min(prices),
            median_price=median(prices),
            offer_count=len(prices),
        )
        session.add(snapshot)
        snapshots.append(snapshot)

    await session.flush()
    return snapshots


async def list_price_snapshots(
    session: AsyncSession,
    category_id: int,
    *,
    server_id: int | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> list[PriceSnapshot]:
    """Return snapshots oldest-first, optionally filtered by server and period."""
    statement = select(PriceSnapshot).where(PriceSnapshot.category_id == category_id)
    if server_id is not None:
        statement = statement.where(PriceSnapshot.server_id == server_id)
    if since is not None:
        statement = statement.where(PriceSnapshot.captured_at >= since)

    statement = statement.order_by(PriceSnapshot.captured_at.desc())
    if limit is not None:
        statement = statement.limit(limit)

    rows = list(await session.scalars(statement))
    rows.reverse()
    return rows


async def start_parse_run(session: AsyncSession, category_id: int) -> ParseRun:
    """Open a parse run before hitting the network, so failures are recorded."""
    run = ParseRun(category_id=category_id, status=PARSE_RUN_RUNNING)
    session.add(run)
    await session.flush()
    return run


async def finish_parse_run(
    session: AsyncSession,
    run: ParseRun,
    *,
    status: str,
    offers_found: int,
    error_text: str | None = None,
) -> None:
    """Finalise a parse run with its outcome."""
    run.status = status
    run.offers_found = offers_found
    run.error_text = error_text[:4000] if error_text else None
    run.finished_at = datetime.now(UTC)


async def get_or_create_user(
    session: AsyncSession,
    vk_id: int,
    first_name: str | None = None,
) -> User:
    """Find a bot user by VK id or create one."""
    user = await session.scalar(select(User).where(User.vk_id == vk_id))
    if user is None:
        user = User(vk_id=vk_id, first_name=first_name)
        session.add(user)
        await session.flush()
    elif first_name and user.first_name != first_name:
        user.first_name = first_name
    return user


async def list_servers(session: AsyncSession, category_id: int) -> list[Server]:
    """Return servers discovered for a category, sorted by name."""
    result = await session.scalars(
        select(Server).where(Server.category_id == category_id).order_by(Server.name)
    )
    return list(result)


async def upsert_subscription(
    session: AsyncSession,
    *,
    user_id: int,
    category_id: int,
    server_id: int | None,
    mode: str,
    threshold: Decimal | None,
) -> Subscription:
    """Create an alert rule or refresh the threshold of an identical active one."""
    statement = select(Subscription).where(
        Subscription.user_id == user_id,
        Subscription.category_id == category_id,
        Subscription.mode == mode,
        Subscription.is_active.is_(True),
    )
    if server_id is None:
        statement = statement.where(Subscription.server_id.is_(None))
    else:
        statement = statement.where(Subscription.server_id == server_id)

    subscription = await session.scalar(statement)
    if subscription is None:
        subscription = Subscription(
            user_id=user_id,
            category_id=category_id,
            server_id=server_id,
            mode=mode,
            threshold=threshold,
            is_active=True,
        )
        session.add(subscription)
    else:
        subscription.threshold = threshold

    await session.flush()
    return subscription


async def list_user_subscriptions(
    session: AsyncSession,
    user_id: int,
) -> list[Subscription]:
    """Return active subscriptions of a user with category and server eager-loaded."""
    result = await session.scalars(
        select(Subscription)
        .where(
            Subscription.user_id == user_id,
            Subscription.is_active.is_(True),
        )
        .options(
            selectinload(Subscription.category),
            selectinload(Subscription.server),
        )
        .order_by(Subscription.id)
    )
    return list(result)


async def get_user_subscription(
    session: AsyncSession,
    subscription_id: int,
    user_id: int,
) -> Subscription | None:
    """Return one user's subscription with category/server preloaded."""
    return await session.scalar(
        select(Subscription)
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user_id,
            Subscription.is_active.is_(True),
        )
        .options(
            selectinload(Subscription.category),
            selectinload(Subscription.server),
        )
    )


async def deactivate_subscription(
    session: AsyncSession,
    subscription_id: int,
    user_id: int,
) -> Subscription | None:
    """Soft-delete a user's subscription; returns it or None if not found."""
    subscription = await get_user_subscription(session, subscription_id, user_id)
    if subscription is not None:
        subscription.is_active = False
    return subscription


async def count_active_subscriptions(session: AsyncSession, user_id: int) -> int:
    """Count active alert rules of a user."""
    result = await session.scalar(
        select(func.count(Subscription.id)).where(
            Subscription.user_id == user_id,
            Subscription.is_active.is_(True),
        )
    )
    return int(result or 0)


async def current_price_summary(
    session: AsyncSession,
    category_id: int,
    server_id: int | None = None,
) -> PriceSummary | None:
    """Compute current min/median/count directly from the offers table."""
    statement = select(Offer.price).where(Offer.category_id == category_id)
    if server_id is not None:
        statement = statement.where(Offer.server_id == server_id)

    prices = list(await session.scalars(statement))
    if not prices:
        return None
    return PriceSummary(
        min_price=min(prices),
        median_price=median(prices),
        offer_count=len(prices),
    )


async def list_aggregated_snapshots(
    session: AsyncSession,
    category_id: int,
    *,
    since: datetime | None = None,
    limit: int | None = None,
) -> list[SnapshotAggregate]:
    """Aggregate per-server snapshots of one parse run into a category-wide series.

    All snapshots written in a single monitoring transaction share the same
    ``captured_at`` because PostgreSQL ``now()`` is transaction-scoped.
    """
    statement = (
        select(
            PriceSnapshot.captured_at,
            func.min(PriceSnapshot.min_price),
            func.avg(PriceSnapshot.median_price),
            func.sum(PriceSnapshot.offer_count),
        )
        .where(PriceSnapshot.category_id == category_id)
        .group_by(PriceSnapshot.captured_at)
        .order_by(PriceSnapshot.captured_at.desc())
    )
    if since is not None:
        statement = statement.where(PriceSnapshot.captured_at >= since)
    if limit is not None:
        statement = statement.limit(limit)

    rows = (await session.execute(statement)).all()
    aggregates = [
        SnapshotAggregate(
            captured_at=row[0],
            min_price=row[1],
            median_price=row[2],
            offer_count=int(row[3]),
        )
        for row in rows
    ]
    aggregates.reverse()
    return aggregates
