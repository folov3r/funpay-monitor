from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.db.models import (
    Notification,
    PriceSnapshot,
    Server,
)
from app.db.repositories import (
    get_or_create_category,
    get_or_create_user,
    upsert_subscription,
)
from app.parsers.base import CategoryInfo
from app.services.alerts import (
    AlertService,
    PendingAlert,
    alert_triggered,
    evaluate_category_alerts,
    format_alert_text,
    percent_drop,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

INFO = CategoryInfo(
    funpay_id=30,
    type="chip",
    title="Серебро Albion Online",
    url_path="/chips/30/",
)

NOW = datetime(2026, 1, 10, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("mode", "threshold", "current", "previous", "historical", "expected"),
    [
        ("abs", Decimal("100"), Decimal("99"), None, None, True),
        ("abs", Decimal("100"), Decimal("100"), None, None, False),
        ("abs", None, Decimal("50"), None, None, False),
        ("pct", Decimal("5"), Decimal("94"), Decimal("100"), None, True),
        ("pct", Decimal("5"), Decimal("96"), Decimal("100"), None, False),
        ("pct", Decimal("5"), Decimal("110"), Decimal("100"), None, False),
        ("pct", Decimal("5"), Decimal("90"), None, None, False),
        ("lowest", None, Decimal("89"), Decimal("95"), Decimal("90"), True),
        ("lowest", None, Decimal("90"), Decimal("95"), Decimal("90"), False),
        ("lowest", None, Decimal("90"), None, None, False),
        ("unknown", None, Decimal("1"), None, None, False),
    ],
)
def test_alert_triggered(
    mode: str,
    threshold: Decimal | None,
    current: Decimal,
    previous: Decimal | None,
    historical: Decimal | None,
    expected: bool,
) -> None:
    assert alert_triggered(mode, threshold, current, previous, historical) is expected


def test_percent_drop() -> None:
    assert percent_drop(Decimal("90"), Decimal("100")) == Decimal("10")
    assert percent_drop(Decimal("90"), Decimal("0")) == Decimal("0")


def make_alert(**overrides: object) -> PendingAlert:
    defaults: dict[str, object] = {
        "subscription_id": 3,
        "user_vk_id": 777,
        "category_id": 1,
        "category_title": "Серебро",
        "server_id": 2,
        "server_name": "EU",
        "mode": "abs",
        "threshold": Decimal("100"),
        "price": Decimal("90"),
        "previous_price": Decimal("120"),
        "historical_min": Decimal("95"),
        "snapshot_id": 10,
    }
    defaults.update(overrides)
    return PendingAlert(**defaults)  # type: ignore[arg-type]


def test_format_alert_text_abs() -> None:
    text = format_alert_text(make_alert())

    assert "Серебро · EU" in text
    assert "Цена ниже порога: 90,00 ₽ (порог 100,00 ₽)." in text
    assert "Было: 120,00 ₽." in text
    assert "Подписка #3" in text


def test_format_alert_text_pct() -> None:
    text = format_alert_text(
        make_alert(
            mode="pct",
            threshold=Decimal("5"),
            price=Decimal("90"),
            previous_price=Decimal("100"),
        )
    )

    assert "Цена упала на 10,0%: 100,00 ₽ → 90,00 ₽." in text


def test_format_alert_text_lowest_and_any_server() -> None:
    text = format_alert_text(
        make_alert(
            mode="lowest",
            threshold=None,
            server_id=None,
            server_name="любой сервер",
            price=Decimal("80"),
            historical_min=Decimal("85"),
        )
    )

    assert "Серебро" in text
    assert "любой сервер" not in text
    assert "Новый исторический минимум: 80,00 ₽." in text
    assert "Предыдущий минимум: 85,00 ₽." in text


async def add_snapshot(
    session: AsyncSession,
    *,
    category_id: int,
    server_id: int,
    captured_at: datetime,
    price: Decimal,
    median: Decimal | None = None,
    count: int = 1,
    item_type: str | None = None,
    query: str | None = None,
) -> PriceSnapshot:
    snapshot = PriceSnapshot(
        category_id=category_id,
        server_id=server_id,
        item_type=item_type,
        query=query,
        min_price=price,
        median_price=median if median is not None else price,
        offer_count=count,
        captured_at=captured_at,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot


async def make_subscription(
    session: AsyncSession,
    *,
    mode: str,
    threshold: Decimal | None = None,
    item_type: str | None = None,
    query: str | None = None,
) -> tuple[int, int, int]:
    user = await get_or_create_user(session, 5001)
    category = await get_or_create_category(session, INFO)
    server = Server(category_id=category.id, funpay_server_id=1, name="EU")
    session.add(server)
    await session.flush()
    subscription = await upsert_subscription(
        session,
        user_id=user.id,
        category_id=category.id,
        server_id=server.id,
        mode=mode,
        threshold=threshold,
        item_type=item_type,
        query=query,
    )
    await session.commit()
    return subscription.id, category.id, server.id


async def test_evaluate_abs_alert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        subscription_id, category_id, server_id = await make_subscription(
            session, mode="abs", threshold=Decimal("100")
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW - timedelta(hours=2),
            price=Decimal("120"),
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW,
            price=Decimal("90"),
        )
        await session.commit()

    async with session_factory() as session:
        alerts = await evaluate_category_alerts(
            session,
            category_id,
            cooldown=timedelta(hours=6),
            now=NOW,
        )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.subscription_id == subscription_id
    assert alert.user_vk_id == 5001
    assert alert.server_name == "EU"
    assert alert.price == Decimal("90")
    assert alert.previous_price == Decimal("120")
    assert alert.historical_min == Decimal("120")


async def test_evaluate_pct_alerts_respect_threshold(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first_user = await get_or_create_user(session, 5001)
        second_user = await get_or_create_user(session, 5002)
        category = await get_or_create_category(session, INFO)
        server = Server(category_id=category.id, funpay_server_id=1, name="EU")
        session.add(server)
        await session.flush()
        await upsert_subscription(
            session,
            user_id=first_user.id,
            category_id=category.id,
            server_id=server.id,
            mode="pct",
            threshold=Decimal("5"),
        )
        await upsert_subscription(
            session,
            user_id=second_user.id,
            category_id=category.id,
            server_id=server.id,
            mode="pct",
            threshold=Decimal("7"),
        )
        await add_snapshot(
            session,
            category_id=category.id,
            server_id=server.id,
            captured_at=NOW - timedelta(hours=2),
            price=Decimal("100"),
        )
        await add_snapshot(
            session,
            category_id=category.id,
            server_id=server.id,
            captured_at=NOW,
            price=Decimal("94"),
        )
        await session.commit()
        category_id = category.id

    async with session_factory() as session:
        alerts = await evaluate_category_alerts(
            session,
            category_id,
            cooldown=timedelta(hours=6),
            now=NOW,
        )

    assert [alert.threshold for alert in alerts] == [Decimal("5")]
    assert alerts[0].previous_price == Decimal("100")


async def test_evaluate_lowest_alert_and_first_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _, category_id, server_id = await make_subscription(session, mode="lowest")
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW - timedelta(hours=2),
            price=Decimal("100"),
        )
        await session.commit()

    async with session_factory() as session:
        first = await evaluate_category_alerts(
            session,
            category_id,
            cooldown=timedelta(hours=6),
            now=NOW,
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW,
            price=Decimal("95"),
        )
        await session.commit()

    async with session_factory() as session:
        second = await evaluate_category_alerts(
            session,
            category_id,
            cooldown=timedelta(hours=6),
            now=NOW,
        )

    assert first == []
    assert len(second) == 1
    assert second[0].historical_min == Decimal("100")


async def test_cooldown_suppresses_alert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        subscription_id, category_id, server_id = await make_subscription(
            session, mode="abs", threshold=Decimal("100")
        )
        snapshot = await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW,
            price=Decimal("90"),
        )
        session.add(
            Notification(
                subscription_id=subscription_id,
                snapshot_id=snapshot.id,
                price=Decimal("90"),
                reason="abs",
                sent_at=NOW - timedelta(hours=1),
            )
        )
        await session.commit()

    async with session_factory() as session:
        alerts = await evaluate_category_alerts(
            session,
            category_id,
            cooldown=timedelta(hours=6),
            now=NOW,
        )

    assert alerts == []


class FakeNotifier:
    def __init__(self) -> None:
        self.sent: list[tuple[PendingAlert, bytes | None]] = []

    async def send(self, alert: PendingAlert, *, chart: bytes | None = None) -> None:
        self.sent.append((alert, chart))


async def test_alert_service_sends_chart_and_logs_notification(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        subscription_id, category_id, server_id = await make_subscription(
            session, mode="abs", threshold=Decimal("100")
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW,
            price=Decimal("90"),
        )
        await session.commit()

    async def fake_chart(self: AlertService, alert: PendingAlert) -> bytes:
        return b"png"

    monkeypatch.setattr(AlertService, "_render_chart", fake_chart)
    notifier = FakeNotifier()
    service = AlertService(session_factory, notifier, cooldown_hours=6)

    sent = await service.process_category(category_id)

    assert len(sent) == 1
    assert notifier.sent[0][1] == b"png"

    async with session_factory() as session:
        logs = list(await session.scalars(select(Notification)))
        assert len(logs) == 1
        assert logs[0].subscription_id == subscription_id
        assert logs[0].price == Decimal("90")
        assert logs[0].reason == "abs"

    assert await service.process_category(category_id) == []


async def test_evaluate_any_server_uses_category_wide_minimum(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        user = await get_or_create_user(session, 6001)
        category = await get_or_create_category(session, INFO)
        eu = Server(category_id=category.id, funpay_server_id=1, name="EU")
        na = Server(category_id=category.id, funpay_server_id=2, name="NA")
        session.add_all([eu, na])
        await session.flush()
        await upsert_subscription(
            session,
            user_id=user.id,
            category_id=category.id,
            server_id=None,
            mode="abs",
            threshold=Decimal("90"),
        )
        await add_snapshot(
            session,
            category_id=category.id,
            server_id=eu.id,
            captured_at=NOW - timedelta(hours=2),
            price=Decimal("100"),
        )
        await add_snapshot(
            session,
            category_id=category.id,
            server_id=na.id,
            captured_at=NOW - timedelta(hours=2),
            price=Decimal("95"),
        )
        await add_snapshot(
            session,
            category_id=category.id,
            server_id=eu.id,
            captured_at=NOW,
            price=Decimal("85"),
        )
        await add_snapshot(
            session,
            category_id=category.id,
            server_id=na.id,
            captured_at=NOW,
            price=Decimal("120"),
        )
        await session.commit()
        category_id = category.id

    async with session_factory() as session:
        alerts = await evaluate_category_alerts(
            session,
            category_id,
            cooldown=timedelta(hours=6),
            now=NOW,
        )

    assert len(alerts) == 1
    assert alerts[0].server_id is None
    assert alerts[0].server_name == "любой сервер"
    assert alerts[0].price == Decimal("85")
    assert alerts[0].previous_price == Decimal("95")


async def test_filtered_alert_uses_only_matching_slice(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        subscription_id, category_id, server_id = await make_subscription(
            session,
            mode="abs",
            threshold=Decimal("100"),
            item_type="предметы",
            query="plush nessie",
        )
        # Unfiltered history is much more expensive and must be ignored.
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW - timedelta(hours=2),
            price=Decimal("300"),
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW,
            price=Decimal("200"),
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW - timedelta(hours=2),
            price=Decimal("120"),
            item_type="предметы",
            query="plush nessie",
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW,
            price=Decimal("90"),
            item_type="предметы",
            query="plush nessie",
        )
        await session.commit()

    async with session_factory() as session:
        alerts = await evaluate_category_alerts(
            session,
            category_id,
            cooldown=timedelta(hours=6),
            now=NOW,
        )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.subscription_id == subscription_id
    assert alert.price == Decimal("90")
    assert alert.previous_price == Decimal("120")
    assert alert.item_type == "предметы"
    assert alert.query == "plush nessie"

    text = format_alert_text(alert)
    assert "Серебро Albion Online · Предметы · «plush nessie» · EU" in text


async def test_stale_filtered_snapshot_does_not_alert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _, category_id, server_id = await make_subscription(
            session,
            mode="abs",
            threshold=Decimal("100"),
            item_type="предметы",
            query="plush nessie",
        )
        # The latest run has no matching offers, so its filtered slice is old.
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW - timedelta(hours=4),
            price=Decimal("150"),
            item_type="предметы",
            query="plush nessie",
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW - timedelta(hours=3),
            price=Decimal("80"),
            item_type="предметы",
            query="plush nessie",
        )
        await add_snapshot(
            session,
            category_id=category_id,
            server_id=server_id,
            captured_at=NOW,
            price=Decimal("200"),
        )
        await session.commit()

    async with session_factory() as session:
        alerts = await evaluate_category_alerts(
            session,
            category_id,
            cooldown=timedelta(hours=6),
            now=NOW,
        )

    assert alerts == []
