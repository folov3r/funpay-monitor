"""Evaluate subscription alert conditions and deliver notifications."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories import (
    add_notification,
    historical_min_price,
    last_notification_at,
    latest_category_captured_at,
    latest_snapshot_point,
    list_aggregated_snapshots,
    list_category_subscriptions,
    list_price_snapshots,
    previous_snapshot_point,
)
from app.services.charts import ChartPoint, render_price_chart_async
from app.services.formatting import format_money, format_offer_filter, format_percent

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PendingAlert:
    """A triggered subscription ready to be delivered."""

    subscription_id: int
    user_vk_id: int
    category_id: int
    category_title: str
    server_id: int | None
    server_name: str
    mode: str
    threshold: Decimal | None
    price: Decimal
    previous_price: Decimal | None
    historical_min: Decimal | None
    snapshot_id: int
    item_type: str | None = None
    query: str | None = None


class AlertNotifier(Protocol):
    """Delivery channel for triggered alerts."""

    async def send(self, alert: PendingAlert, *, chart: bytes | None = None) -> None: ...


def alert_triggered(
    mode: str,
    threshold: Decimal | None,
    current_min: Decimal,
    previous_min: Decimal | None,
    historical_min: Decimal | None,
) -> bool:
    """Return whether one snapshot satisfies the subscription condition.

    ``lowest`` never fires on the very first snapshot: without history there
    is no meaningful "new minimum" yet.
    """
    if mode == "abs":
        return threshold is not None and current_min < threshold
    if mode == "pct":
        if threshold is None or previous_min is None or previous_min <= 0:
            return False
        drop = (previous_min - current_min) / previous_min * Decimal(100)
        return current_min < previous_min and drop >= threshold
    if mode == "lowest":
        return historical_min is not None and current_min < historical_min
    return False


def percent_drop(current: Decimal, previous: Decimal) -> Decimal:
    """Return how much the price fell relative to the previous value."""
    if previous <= 0:
        return Decimal(0)
    return (previous - current) / previous * Decimal(100)


def format_alert_text(alert: PendingAlert) -> str:
    """Build the Russian notification body sent to VK."""
    title = f"🔔 {alert.category_title}"
    filter_label = format_offer_filter(alert.item_type, alert.query)
    if filter_label:
        title = f"{title} · {filter_label}"
    if alert.server_name and alert.server_name != "любой сервер":
        title = f"{title} · {alert.server_name}"

    lines = [title]
    if alert.mode == "abs":
        lines.append(
            f"Цена ниже порога: {format_money(alert.price)} "
            f"(порог {format_money(alert.threshold)})."
        )
    elif alert.mode == "pct":
        previous = alert.previous_price
        drop = percent_drop(alert.price, previous) if previous is not None else Decimal(0)
        lines.append(
            f"Цена упала на {format_percent(drop)}: "
            f"{format_money(previous)} → {format_money(alert.price)}."
        )
    else:
        lines.append(f"Новый исторический минимум: {format_money(alert.price)}.")

    if alert.mode == "abs" and alert.previous_price is not None:
        lines.append(f"Было: {format_money(alert.previous_price)}.")
    if alert.mode == "lowest" and alert.historical_min is not None:
        lines.append(f"Предыдущий минимум: {format_money(alert.historical_min)}.")

    lines.append("")
    lines.append(f"Подписка #{alert.subscription_id} · FunPay Monitor")
    return "\n".join(lines)


async def evaluate_category_alerts(
    session: AsyncSession,
    category_id: int,
    *,
    cooldown: timedelta,
    now: datetime | None = None,
) -> list[PendingAlert]:
    """Return all active subscriptions of a category that must be notified."""
    moment = now or datetime.now(UTC)
    subscriptions = await list_category_subscriptions(session, category_id)
    latest_run_at = await latest_category_captured_at(session, category_id)
    alerts: list[PendingAlert] = []

    for subscription in subscriptions:
        current = await latest_snapshot_point(
            session,
            category_id,
            subscription.server_id,
            item_type=subscription.item_type,
            query=subscription.query,
        )
        if current is None:
            continue
        # A filtered slice may have no offers in the latest run. Do not alert
        # on an old snapshot that is no longer part of the current run.
        if latest_run_at is not None and current.captured_at < latest_run_at:
            continue

        last_sent = await last_notification_at(session, subscription.id)
        if last_sent is not None and moment - last_sent < cooldown:
            continue

        previous = await previous_snapshot_point(
            session,
            category_id,
            subscription.server_id,
            current.captured_at,
            item_type=subscription.item_type,
            query=subscription.query,
        )
        historical = await historical_min_price(
            session,
            category_id,
            subscription.server_id,
            current.captured_at,
            item_type=subscription.item_type,
            query=subscription.query,
        )

        if not alert_triggered(
            subscription.mode,
            subscription.threshold,
            current.min_price,
            previous.min_price if previous is not None else None,
            historical,
        ):
            continue

        alerts.append(
            PendingAlert(
                subscription_id=subscription.id,
                user_vk_id=subscription.user.vk_id,
                category_id=category_id,
                category_title=subscription.category.title,
                server_id=subscription.server_id,
                server_name=(
                    subscription.server.name if subscription.server is not None else "любой сервер"
                ),
                mode=subscription.mode,
                threshold=subscription.threshold,
                price=current.min_price,
                previous_price=previous.min_price if previous is not None else None,
                historical_min=historical,
                snapshot_id=current.snapshot_id,
                item_type=subscription.item_type,
                query=subscription.query,
            )
        )

    return alerts


class AlertService:
    """Check subscriptions after a parse run, send alerts and log them."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        notifier: AlertNotifier,
        *,
        cooldown_hours: int = 6,
        history_days: int = 7,
    ) -> None:
        self._session_factory = session_factory
        self._notifier = notifier
        self._cooldown = timedelta(hours=cooldown_hours)
        self._history_days = history_days

    async def process_category(self, category_id: int) -> list[PendingAlert]:
        """Evaluate one category and deliver every alert that passes the cooldown."""
        async with self._session_factory() as session:
            alerts = await evaluate_category_alerts(
                session,
                category_id,
                cooldown=self._cooldown,
            )

        if not alerts:
            return []

        sent: list[PendingAlert] = []
        for alert in alerts:
            chart = await self._render_chart(alert)
            try:
                await self._notifier.send(alert, chart=chart)
            except Exception:
                logger.exception(
                    "Could not send alert #%s to VK user %s",
                    alert.subscription_id,
                    alert.user_vk_id,
                )
                continue
            sent.append(alert)

        if sent:
            async with self._session_factory() as session:
                for alert in sent:
                    add_notification(
                        session,
                        subscription_id=alert.subscription_id,
                        snapshot_id=alert.snapshot_id,
                        price=alert.price,
                        reason=alert.mode,
                    )
                await session.commit()
            logger.info("Sent %s alerts for category %s", len(sent), category_id)

        return sent

    async def _render_chart(self, alert: PendingAlert) -> bytes | None:
        since = datetime.now(UTC) - timedelta(days=self._history_days)
        try:
            async with self._session_factory() as session:
                points = await _load_chart_points(session, alert, since)
            if not points:
                return None
            filter_label = format_offer_filter(alert.item_type, alert.query)
            title_parts = [alert.category_title]
            if filter_label:
                title_parts.append(filter_label)
            title_parts.append(alert.server_name)
            return await render_price_chart_async(
                points,
                title=" · ".join(title_parts),
            )
        except Exception:
            logger.exception("Could not render chart for alert #%s", alert.subscription_id)
            return None


async def _load_chart_points(
    session: AsyncSession,
    alert: PendingAlert,
    since: datetime,
) -> Sequence[ChartPoint]:
    if alert.server_id is None:
        aggregates = await list_aggregated_snapshots(
            session,
            alert.category_id,
            item_type=alert.item_type,
            query=alert.query,
            since=since,
        )
        return [
            ChartPoint(
                captured_at=aggregate.captured_at,
                min_price=aggregate.min_price,
                median_price=aggregate.median_price,
            )
            for aggregate in aggregates
        ]

    snapshots = await list_price_snapshots(
        session,
        alert.category_id,
        server_id=alert.server_id,
        item_type=alert.item_type,
        query=alert.query,
        since=since,
    )
    return [
        ChartPoint(
            captured_at=snapshot.captured_at,
            min_price=snapshot.min_price,
            median_price=snapshot.median_price,
        )
        for snapshot in snapshots
    ]
