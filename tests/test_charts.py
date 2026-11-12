from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from app.services.charts import ChartPoint, render_price_chart, render_price_chart_async

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def make_point(day: int, min_price: str, median_price: str) -> ChartPoint:
    return ChartPoint(
        captured_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day),
        min_price=Decimal(min_price),
        median_price=Decimal(median_price),
    )


def test_render_price_chart_returns_png() -> None:
    points = [
        make_point(0, "10.50", "12.00"),
        make_point(1, "9.80", "11.40"),
        make_point(2, "9.95", "11.10"),
    ]

    image = render_price_chart(points, title="Серебро Albion Online · EU")

    assert image.startswith(PNG_SIGNATURE)
    assert len(image) > 1000


def test_render_price_chart_handles_single_point() -> None:
    image = render_price_chart([make_point(0, "10.50", "12.00")], title="One point")

    assert image.startswith(PNG_SIGNATURE)


def test_render_price_chart_rejects_empty_history() -> None:
    with pytest.raises(ValueError, match="empty price history"):
        render_price_chart([], title="Nothing")


async def test_render_price_chart_async() -> None:
    image = await render_price_chart_async(
        [make_point(0, "10.50", "12.00"), make_point(1, "9.80", "11.40")],
        title="Async chart",
        currency="USD",
    )

    assert image.startswith(PNG_SIGNATURE)
