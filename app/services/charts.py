"""Render price history as a PNG chart for VK messages."""

from __future__ import annotations

import asyncio
import io
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import matplotlib

matplotlib.use("Agg")

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

_RENDER_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class ChartPoint:
    """One aggregated price snapshot used for plotting."""

    captured_at: datetime
    min_price: Decimal
    median_price: Decimal


def render_price_chart(
    points: Sequence[ChartPoint],
    *,
    title: str,
    currency: str = "RUB",
) -> bytes:
    """Render min/median price history to PNG bytes.

    Matplotlib is not thread-safe, so all rendering is serialised by a lock.
    Call :func:`render_price_chart_async` from async code to avoid blocking
    the event loop.
    """
    if not points:
        raise ValueError("cannot render an empty price history")

    ordered = sorted(points, key=lambda point: point.captured_at)
    moments = [_naive_utc(point.captured_at) for point in ordered]
    min_prices = [float(point.min_price) for point in ordered]
    median_prices = [float(point.median_price) for point in ordered]

    with _RENDER_LOCK:
        figure, axis = plt.subplots(figsize=(8, 4.5), dpi=120)
        try:
            axis.plot(
                moments,
                min_prices,
                color="#2e7d32",
                marker="o",
                markersize=3,
                linewidth=1.8,
                label="Мин. цена",
            )
            axis.plot(
                moments,
                median_prices,
                color="#1565c0",
                marker="s",
                markersize=3,
                linewidth=1.5,
                linestyle="--",
                label="Медиана",
            )
            if len(moments) > 1:
                axis.fill_between(moments, min_prices, median_prices, color="#90caf9", alpha=0.2)

            axis.set_title(title, fontsize=12, pad=12)
            axis.set_ylabel(f"Цена, {currency}")
            axis.grid(True, alpha=0.3)
            axis.legend(loc="best")
            axis.xaxis.set_major_locator(mdates.AutoDateLocator())
            axis.xaxis.set_major_formatter(
                mdates.ConciseDateFormatter(axis.xaxis.get_major_locator())
            )
            figure.autofmt_xdate()
            figure.tight_layout()

            buffer = io.BytesIO()
            figure.savefig(buffer, format="png")
            return buffer.getvalue()
        finally:
            plt.close(figure)


async def render_price_chart_async(
    points: Sequence[ChartPoint],
    *,
    title: str,
    currency: str = "RUB",
) -> bytes:
    """Render a chart in a worker thread so the event loop stays responsive."""
    return await asyncio.to_thread(
        render_price_chart,
        points,
        title=title,
        currency=currency,
    )


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment
    return moment.astimezone(UTC).replace(tzinfo=None)
