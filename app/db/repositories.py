"""Database access helpers used by the worker and bot."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from statistics import median

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    Category,
    Notification,
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
class SnapshotFilter:
    """One offer slice that needs its own price history.

    ``server_id`` is the database id of the server, or ``None`` for "any
    server". ``item_type`` and ``query`` are the optional user filters; their
    ``None`` values are meaningful and match unfiltered snapshots.
    """

    server_id: int | None
    item_type: str | None = None
    query: str | None = None


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


@dataclass(frozen=True, slots=True)
class SnapshotPoint:
    """One snapshot value used to evaluate alert conditions."""

    snapshot_id: int
    captured_at: datetime
    min_price: Decimal
    median_price: Decimal
    offer_count: int


@dataclass(frozen=True, slots=True)
class ParseRunStatus:
    """A parse run joined with its category, used by admin /status."""

    category_id: int
    category_title: str
    category_path: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    offers_found: int
    error_text: str | None


@dataclass(frozen=True, slots=True)
class AdminStats:
    """Aggregate counters for admin /status."""

    categories: int
    active_categories: int
    users: int
    active_subscriptions: int
    offers: int


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


def _offer_matches(offer: ParsedOffer, item_type: str | None, query: str | None) -> bool:
    """Return whether an offer belongs to the requested type/title slice."""
    if item_type is not None and (offer.item_type or "").casefold() != item_type.casefold():
        return False
    return query is None or query.casefold() in (offer.title or "").casefold()


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
            item_type=offer.item_type,
            method=offer.method,
            title=offer.title,
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
    filters: Iterable[SnapshotFilter] = (),
) -> list[PriceSnapshot]:
    """Write snapshots for the whole category and for every requested slice.

    The unfiltered per-server snapshots are always written. Additional rows are
    created for each active subscription slice so alerts and charts can use a
    history that matches the user's type/title filter.
    """
    funpay_by_orm_id = {server.id: funpay_id for funpay_id, server in servers.items()}
    created: set[tuple[int, str | None, str | None]] = set()
    snapshots: list[PriceSnapshot] = []

    def grouped_prices(
        item_type: str | None,
        query: str | None,
    ) -> dict[int, list[Decimal]]:
        prices: dict[int, list[Decimal]] = defaultdict(list)
        for offer in offers:
            if _offer_matches(offer, item_type, query):
                prices[offer.server_id].append(offer.price)
        return prices

    def add_slice(
        server_id: int,
        item_type: str | None,
        query: str | None,
        prices: list[Decimal],
    ) -> None:
        key = (server_id, item_type, query)
        if key in created or not prices:
            return
        created.add(key)
        snapshot = PriceSnapshot(
            category_id=category_id,
            server_id=server_id,
            item_type=item_type,
            query=query,
            min_price=min(prices),
            median_price=median(prices),
            offer_count=len(prices),
        )
        session.add(snapshot)
        snapshots.append(snapshot)

    for funpay_server_id, prices in grouped_prices(None, None).items():
        add_slice(servers[funpay_server_id].id, None, None, prices)

    for snapshot_filter in filters:
        if (
            snapshot_filter.server_id is None
            and snapshot_filter.item_type is None
            and snapshot_filter.query is None
        ):
            continue

        prices_by_server = grouped_prices(snapshot_filter.item_type, snapshot_filter.query)
        if snapshot_filter.server_id is not None:
            funpay_server_id = funpay_by_orm_id.get(snapshot_filter.server_id)
            if funpay_server_id is None:
                continue
            add_slice(
                snapshot_filter.server_id,
                snapshot_filter.item_type,
                snapshot_filter.query,
                prices_by_server.get(funpay_server_id, []),
            )
            continue

        for funpay_server_id, prices in prices_by_server.items():
            add_slice(
                servers[funpay_server_id].id,
                snapshot_filter.item_type,
                snapshot_filter.query,
                prices,
            )

    await session.flush()
    return snapshots


async def list_price_snapshots(
    session: AsyncSession,
    category_id: int,
    *,
    server_id: int | None = None,
    item_type: str | None = None,
    query: str | None = None,
    since: datetime | None = None,
    limit: int | None = None,
) -> list[PriceSnapshot]:
    """Return snapshots oldest-first for one server/type/title slice.

    ``item_type=None`` and ``query=None`` select unfiltered snapshots rather
    than disabling the filter, because filtered and unfiltered history are
    stored side by side.
    """
    statement = select(PriceSnapshot).where(PriceSnapshot.category_id == category_id)
    if server_id is not None:
        statement = statement.where(PriceSnapshot.server_id == server_id)
    statement = statement.where(
        PriceSnapshot.item_type.is_(None)
        if item_type is None
        else PriceSnapshot.item_type == item_type
    )
    statement = statement.where(
        PriceSnapshot.query.is_(None) if query is None else PriceSnapshot.query == query
    )
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
    item_type: str | None = None,
    query: str | None = None,
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
    statement = statement.where(
        Subscription.item_type.is_(None)
        if item_type is None
        else Subscription.item_type == item_type
    )
    statement = statement.where(
        Subscription.query.is_(None) if query is None else Subscription.query == query
    )

    subscription = await session.scalar(statement)
    if subscription is None:
        subscription = Subscription(
            user_id=user_id,
            category_id=category_id,
            server_id=server_id,
            item_type=item_type,
            query=query,
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
    *,
    item_type: str | None = None,
    query: str | None = None,
) -> PriceSummary | None:
    """Compute current min/median/count directly from the offers table."""
    statement = select(Offer.price).where(Offer.category_id == category_id)
    if server_id is not None:
        statement = statement.where(Offer.server_id == server_id)
    if item_type is not None:
        statement = statement.where(Offer.item_type == item_type)
    if query is not None:
        statement = statement.where(
            func.lower(Offer.title).contains(query.casefold(), autoescape=True)
        )

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
    item_type: str | None = None,
    query: str | None = None,
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
        .where(
            PriceSnapshot.item_type.is_(None)
            if item_type is None
            else PriceSnapshot.item_type == item_type
        )
        .where(PriceSnapshot.query.is_(None) if query is None else PriceSnapshot.query == query)
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


async def list_category_subscriptions(
    session: AsyncSession,
    category_id: int,
) -> list[Subscription]:
    """Return active subscriptions of a category with user/category/server loaded."""
    result = await session.scalars(
        select(Subscription)
        .where(
            Subscription.category_id == category_id,
            Subscription.is_active.is_(True),
        )
        .options(
            selectinload(Subscription.user),
            selectinload(Subscription.category),
            selectinload(Subscription.server),
        )
        .order_by(Subscription.id)
    )
    return list(result)


async def list_category_snapshot_filters(
    session: AsyncSession,
    category_id: int,
) -> list[SnapshotFilter]:
    """Return distinct slices that active subscriptions of a category need."""
    rows = (
        await session.execute(
            select(Subscription.server_id, Subscription.item_type, Subscription.query)
            .where(
                Subscription.category_id == category_id,
                Subscription.is_active.is_(True),
            )
            .distinct()
        )
    ).all()
    return [
        SnapshotFilter(server_id=server_id, item_type=item_type, query=query)
        for server_id, item_type, query in rows
    ]


async def _category_snapshot_at(
    session: AsyncSession,
    category_id: int,
    captured_at: datetime,
    *,
    item_type: str | None = None,
    query: str | None = None,
) -> SnapshotPoint | None:
    row = (
        await session.execute(
            select(
                func.max(PriceSnapshot.id),
                func.min(PriceSnapshot.min_price),
                func.avg(PriceSnapshot.median_price),
                func.sum(PriceSnapshot.offer_count),
            ).where(
                PriceSnapshot.category_id == category_id,
                PriceSnapshot.captured_at == captured_at,
                PriceSnapshot.item_type.is_(None)
                if item_type is None
                else PriceSnapshot.item_type == item_type,
                PriceSnapshot.query.is_(None) if query is None else PriceSnapshot.query == query,
            )
        )
    ).one()
    if row[0] is None:
        return None
    return SnapshotPoint(
        snapshot_id=int(row[0]),
        captured_at=captured_at,
        min_price=row[1],
        median_price=row[2],
        offer_count=int(row[3]),
    )


async def latest_snapshot_point(
    session: AsyncSession,
    category_id: int,
    server_id: int | None = None,
    *,
    item_type: str | None = None,
    query: str | None = None,
) -> SnapshotPoint | None:
    """Return the newest snapshot for a category or one server.

    For a category without a server the per-server snapshots of the newest
    run are aggregated into one point.
    """
    if server_id is not None:
        row = await session.scalar(
            select(PriceSnapshot)
            .where(
                PriceSnapshot.category_id == category_id,
                PriceSnapshot.server_id == server_id,
                PriceSnapshot.item_type.is_(None)
                if item_type is None
                else PriceSnapshot.item_type == item_type,
                PriceSnapshot.query.is_(None) if query is None else PriceSnapshot.query == query,
            )
            .order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        return SnapshotPoint(
            snapshot_id=row.id,
            captured_at=row.captured_at,
            min_price=row.min_price,
            median_price=row.median_price,
            offer_count=row.offer_count,
        )

    captured_at = await session.scalar(
        select(func.max(PriceSnapshot.captured_at))
        .where(PriceSnapshot.category_id == category_id)
        .where(
            PriceSnapshot.item_type.is_(None)
            if item_type is None
            else PriceSnapshot.item_type == item_type
        )
        .where(PriceSnapshot.query.is_(None) if query is None else PriceSnapshot.query == query)
    )
    if captured_at is None:
        return None
    return await _category_snapshot_at(
        session,
        category_id,
        captured_at,
        item_type=item_type,
        query=query,
    )


async def previous_snapshot_point(
    session: AsyncSession,
    category_id: int,
    server_id: int | None,
    before: datetime,
    *,
    item_type: str | None = None,
    query: str | None = None,
) -> SnapshotPoint | None:
    """Return the newest snapshot strictly older than ``before``."""
    if server_id is not None:
        row = await session.scalar(
            select(PriceSnapshot)
            .where(
                PriceSnapshot.category_id == category_id,
                PriceSnapshot.server_id == server_id,
                PriceSnapshot.captured_at < before,
                PriceSnapshot.item_type.is_(None)
                if item_type is None
                else PriceSnapshot.item_type == item_type,
                PriceSnapshot.query.is_(None) if query is None else PriceSnapshot.query == query,
            )
            .order_by(PriceSnapshot.captured_at.desc(), PriceSnapshot.id.desc())
            .limit(1)
        )
        if row is None:
            return None
        return SnapshotPoint(
            snapshot_id=row.id,
            captured_at=row.captured_at,
            min_price=row.min_price,
            median_price=row.median_price,
            offer_count=row.offer_count,
        )

    captured_at = await session.scalar(
        select(func.max(PriceSnapshot.captured_at))
        .where(
            PriceSnapshot.category_id == category_id,
            PriceSnapshot.captured_at < before,
        )
        .where(
            PriceSnapshot.item_type.is_(None)
            if item_type is None
            else PriceSnapshot.item_type == item_type
        )
        .where(PriceSnapshot.query.is_(None) if query is None else PriceSnapshot.query == query)
    )
    if captured_at is None:
        return None
    return await _category_snapshot_at(
        session,
        category_id,
        captured_at,
        item_type=item_type,
        query=query,
    )


async def historical_min_price(
    session: AsyncSession,
    category_id: int,
    server_id: int | None,
    before: datetime,
    *,
    item_type: str | None = None,
    query: str | None = None,
) -> Decimal | None:
    """Return the lowest price seen before ``before``."""
    statement = select(func.min(PriceSnapshot.min_price)).where(
        PriceSnapshot.category_id == category_id,
        PriceSnapshot.captured_at < before,
    )
    if server_id is not None:
        statement = statement.where(PriceSnapshot.server_id == server_id)
    statement = statement.where(
        PriceSnapshot.item_type.is_(None)
        if item_type is None
        else PriceSnapshot.item_type == item_type
    )
    statement = statement.where(
        PriceSnapshot.query.is_(None) if query is None else PriceSnapshot.query == query
    )
    return await session.scalar(statement)


async def latest_category_captured_at(
    session: AsyncSession,
    category_id: int,
) -> datetime | None:
    """Return the moment of the newest parse run for a category."""
    return await session.scalar(
        select(func.max(PriceSnapshot.captured_at)).where(PriceSnapshot.category_id == category_id)
    )


async def last_notification_at(
    session: AsyncSession,
    subscription_id: int,
) -> datetime | None:
    """Return when an alert for this subscription was last sent."""
    return await session.scalar(
        select(func.max(Notification.sent_at)).where(
            Notification.subscription_id == subscription_id
        )
    )


def add_notification(
    session: AsyncSession,
    *,
    subscription_id: int,
    snapshot_id: int,
    price: Decimal,
    reason: str,
) -> Notification:
    """Schedule a notification log row in the current transaction."""
    notification = Notification(
        subscription_id=subscription_id,
        snapshot_id=snapshot_id,
        price=price,
        reason=reason,
    )
    session.add(notification)
    return notification


async def get_admin_stats(session: AsyncSession) -> AdminStats:
    """Collect the counters shown by admin /status."""
    categories = await session.scalar(select(func.count(Category.id)))
    active_categories = await session.scalar(
        select(func.count(Category.id)).where(Category.is_active.is_(True))
    )
    users = await session.scalar(select(func.count(User.id)))
    active_subscriptions = await session.scalar(
        select(func.count(Subscription.id)).where(Subscription.is_active.is_(True))
    )
    offers = await session.scalar(select(func.count(Offer.id)))
    return AdminStats(
        categories=int(categories or 0),
        active_categories=int(active_categories or 0),
        users=int(users or 0),
        active_subscriptions=int(active_subscriptions or 0),
        offers=int(offers or 0),
    )


async def list_recent_parse_runs(
    session: AsyncSession,
    *,
    limit: int = 5,
) -> list[ParseRunStatus]:
    """Return the latest parse runs with category titles for admin /status."""
    rows = (
        await session.execute(
            select(ParseRun, Category.title, Category.url_path)
            .join(Category, ParseRun.category_id == Category.id)
            .order_by(ParseRun.started_at.desc(), ParseRun.id.desc())
            .limit(limit)
        )
    ).all()
    return [
        ParseRunStatus(
            category_id=run.category_id,
            category_title=title,
            category_path=url_path,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            offers_found=run.offers_found,
            error_text=run.error_text,
        )
        for run, title, url_path in rows
    ]


async def fail_stale_parse_runs(
    session: AsyncSession,
    *,
    older_than: datetime,
) -> int:
    """Mark runs stuck in ``running`` as failed after a worker restart."""
    result = await session.execute(
        update(ParseRun)
        .where(
            ParseRun.status == PARSE_RUN_RUNNING,
            ParseRun.started_at < older_than,
        )
        .values(
            status=PARSE_RUN_ERROR,
            finished_at=datetime.now(UTC),
            error_text="interrupted by worker restart",
        )
    )
    return int(result.rowcount or 0)
