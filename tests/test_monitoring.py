from decimal import Decimal

from app.db.models import Category, Offer, ParseRun, PriceSnapshot
from app.db.repositories import get_or_create_category
from app.parsers.base import BaseParser, CategoryInfo, ParsedCategory
from app.parsers.base import Offer as ParsedOffer
from app.services.monitoring import MonitoringService
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INFO = CategoryInfo(
    funpay_id=30,
    type="chip",
    title="Серебро Albion Online",
    url_path="/chips/30/",
)


class FakeParser(BaseParser):
    def __init__(
        self,
        *,
        result: ParsedCategory | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    async def fetch_category(self, url_path: str) -> ParsedCategory:
        self.calls += 1
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result

    async def aclose(self) -> None:
        return None


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


def parsed_result(offers: list[ParsedOffer]) -> ParsedCategory:
    return ParsedCategory(category=INFO, offers=offers)


async def seed_category(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        category = await get_or_create_category(session, INFO)
        await session.commit()
        return category.id


async def test_run_all_active_persists_offers_and_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    category_id = await seed_category(session_factory)
    parser = FakeParser(
        result=parsed_result(
            [
                parsed_offer(server_id=1, server_name="EU", price=Decimal("10")),
                parsed_offer(server_id=1, server_name="EU", price=Decimal("20")),
                parsed_offer(server_id=2, server_name="NA", price=Decimal("30")),
            ]
        )
    )
    monitoring = MonitoringService(parser, session_factory)

    outcomes = await monitoring.run_all_active()

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.category_id == category_id
    assert outcome.status == "ok"
    assert outcome.offers_found == 3
    assert outcome.snapshots_created == 2
    assert outcome.error_text is None

    async with session_factory() as session:
        offers = list(await session.scalars(select(Offer)))
        snapshots = list(await session.scalars(select(PriceSnapshot)))
        run = await session.scalar(select(ParseRun))
        category = await session.get(Category, category_id)

    assert len(offers) == 3
    assert len(snapshots) == 2
    assert run is not None
    assert run.status == "ok"
    assert run.offers_found == 3
    assert run.finished_at is not None
    assert category is not None
    assert category.last_parsed_at is not None


async def test_parse_failure_is_recorded(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_category(session_factory)
    parser = FakeParser(error=RuntimeError("boom"))
    monitoring = MonitoringService(parser, session_factory)

    outcomes = await monitoring.run_all_active()

    assert len(outcomes) == 1
    assert outcomes[0].status == "error"
    assert "boom" in (outcomes[0].error_text or "")

    async with session_factory() as session:
        run = await session.scalar(select(ParseRun))
        offers = list(await session.scalars(select(Offer)))

    assert run is not None
    assert run.status == "error"
    assert run.offers_found == 0
    assert run.finished_at is not None
    assert "boom" in (run.error_text or "")
    assert offers == []


async def test_empty_page_marks_run_as_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await seed_category(session_factory)
    parser = FakeParser(result=parsed_result([]))
    monitoring = MonitoringService(parser, session_factory)

    outcomes = await monitoring.run_all_active()

    assert outcomes[0].status == "error"
    assert "no offers found" in (outcomes[0].error_text or "")

    async with session_factory() as session:
        run = await session.scalar(select(ParseRun))

    assert run is not None
    assert run.status == "error"
    assert run.offers_found == 0


async def test_inactive_categories_are_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    category_id = await seed_category(session_factory)
    async with session_factory() as session:
        category = await session.get(Category, category_id)
        assert category is not None
        category.is_active = False
        await session.commit()

    parser = FakeParser(result=parsed_result([]))
    monitoring = MonitoringService(parser, session_factory)

    outcomes = await monitoring.run_all_active()

    assert outcomes == []
    assert parser.calls == 0


async def test_run_category_by_id_returns_none_for_missing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    monitoring = MonitoringService(FakeParser(result=parsed_result([])), session_factory)

    assert await monitoring.run_category_by_id(999999) is None


async def test_import_category_persists_unknown_category(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    parser = FakeParser(
        result=parsed_result(
            [
                parsed_offer(server_id=1, server_name="EU", price=Decimal("10")),
                parsed_offer(server_id=2, server_name="NA", price=Decimal("20")),
            ]
        )
    )
    monitoring = MonitoringService(parser, session_factory)

    imported = await monitoring.import_category("/chips/30/")

    assert imported.title == "Серебро Albion Online"
    assert imported.url_path == "/chips/30/"
    assert imported.offers_found == 2
    assert imported.snapshots_created == 2

    async with session_factory() as session:
        category = await session.get(Category, imported.category_id)
        offers = list(await session.scalars(select(Offer)))
        snapshots = list(await session.scalars(select(PriceSnapshot)))
        run = await session.scalar(select(ParseRun))

    assert category is not None
    assert category.last_parsed_at is not None
    assert len(offers) == 2
    assert len(snapshots) == 2
    assert run is not None
    assert run.status == "ok"
    assert run.offers_found == 2
