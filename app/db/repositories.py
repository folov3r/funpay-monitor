"""Database access helpers used by the worker and bot."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from statistics import median

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Offer, ParseRun, PriceSnapshot, Server
from app.parsers.base import CategoryInfo
from app.parsers.base import Offer as ParsedOffer

PARSE_RUN_RUNNING = "running"
PARSE_RUN_OK = "ok"
PARSE_RUN_ERROR = "error"
PARSE_RUN_PARTIAL = "partial"


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
