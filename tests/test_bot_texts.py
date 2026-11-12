from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.bot.texts import (
    extract_category_path,
    format_condition,
    format_money,
    format_stats_text,
    format_subscription_list,
    is_add_command,
    is_cancel,
    is_list_command,
    is_stats_command,
    is_unsubscribe_command,
    mode_from_label,
    normalize_text,
    parse_subscription_id,
    parse_threshold,
    split_command,
)
from app.db.repositories import PriceSummary
from app.services.charts import ChartPoint


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://funpay.com/chips/30/", "/chips/30/"),
        ("Добавить https://funpay.com/lots/13/?sort=price", "/lots/13/"),
        ("/chips/30/", "/chips/30/"),
        ("просто текст", None),
        ("https://funpay.com/", None),
    ],
)
def test_extract_category_path(text: str, expected: str | None) -> None:
    assert extract_category_path(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/add", ("/add", "")),
        ("/add https://funpay.com/chips/30/", ("/add", "https://funpay.com/chips/30/")),
        ("/start@my_bot", ("/start", "")),
        ("", ("", "")),
    ],
)
def test_split_command(text: str, expected: tuple[str, str]) -> None:
    assert split_command(text) == expected


def test_normalize_text_collapses_spaces_and_case() -> None:
    assert normalize_text("  Мои   ПОДПИСКИ ") == "мои подписки"


@pytest.mark.parametrize(
    ("text", "predicate"),
    [
        ("/add", is_add_command),
        ("Добавить", is_add_command),
        ("/list", is_list_command),
        ("Мои подписки", is_list_command),
        ("/stats 3", is_stats_command),
        ("Статистика #3", is_stats_command),
        ("/unsubscribe 3", is_unsubscribe_command),
        ("Удалить #3", is_unsubscribe_command),
        ("Отмена", is_cancel),
        ("назад", is_cancel),
    ],
)
def test_command_predicates(text: str, predicate: object) -> None:
    assert predicate(text)  # type: ignore[operator]


@pytest.mark.parametrize("text", ["/list", "stats 3", "добавление", "привет"])
def test_command_predicates_reject_unrelated_text(text: str) -> None:
    assert not is_add_command(text)
    assert not is_stats_command(text)
    assert not is_unsubscribe_command(text)
    assert not is_cancel(text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("3", 3),
        ("#12", 12),
        ("Статистика #7", 7),
        ("нет номера", None),
        ("", None),
    ],
)
def test_parse_subscription_id(raw: str, expected: int | None) -> None:
    assert parse_subscription_id(raw) == expected


@pytest.mark.parametrize(
    ("text", "mode", "expected"),
    [
        ("100", "abs", Decimal("100")),
        ("1 450,50", "abs", Decimal("1450.50")),
        ("7,5", "pct", Decimal("7.5")),
        ("101", "pct", None),
        ("0", "abs", None),
        ("-5", "abs", None),
        ("abc", "abs", None),
    ],
)
def test_parse_threshold(text: str, mode: str, expected: Decimal | None) -> None:
    assert parse_threshold(text, mode) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Ниже порога", "abs"),
        ("Падение в %", "pct"),
        ("Исторический минимум", "lowest"),
        ("Минимум", "lowest"),
        ("что-то", None),
    ],
)
def test_mode_from_label(label: str, expected: str | None) -> None:
    assert mode_from_label(label) == expected


def test_format_money() -> None:
    assert format_money(Decimal("1234.5")) == "1 234,50 ₽"
    assert format_money(None) == "—"


def test_format_condition() -> None:
    assert format_condition("abs", Decimal("100")) == "цена ниже 100,00 ₽"
    assert format_condition("pct", Decimal("7.5")) == "падение на 7.5%"
    assert format_condition("lowest", None) == "новый исторический минимум"


def make_subscription(
    *,
    subscription_id: int = 1,
    mode: str = "abs",
    threshold: Decimal | None = Decimal("100"),
    server_name: str | None = "EU",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=subscription_id,
        mode=mode,
        threshold=threshold,
        category=SimpleNamespace(title="Серебро"),
        server=SimpleNamespace(name=server_name) if server_name else None,
    )


def test_format_subscription_list() -> None:
    subscriptions = [make_subscription(), make_subscription(subscription_id=2, server_name=None)]
    summaries = {1: PriceSummary(Decimal("95"), Decimal("110"), 12)}

    text = format_subscription_list(subscriptions, summaries)

    assert "#1 · Серебро" in text
    assert "EU" in text
    assert "сейчас 95,00 ₽" in text
    assert "#2 · Серебро" in text
    assert "любой сервер" in text
    assert "нет данных о цене" in text


def test_format_subscription_list_when_empty() -> None:
    assert "пока нет активных подписок" in format_subscription_list([], {})


def test_format_stats_text_with_history() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    subscription = make_subscription()
    points = [
        ChartPoint(now, Decimal("100"), Decimal("120")),
        ChartPoint(now + timedelta(days=1), Decimal("90"), Decimal("110")),
    ]

    text = format_stats_text(
        subscription,
        PriceSummary(Decimal("90"), Decimal("105"), 8),
        points,
    )

    assert "#1 · Серебро" in text
    assert "Сервер: EU" in text
    assert "Условие: цена ниже 100,00 ₽" in text
    assert "Сейчас: 90,00 ₽" in text
    assert "За 7 дн.: минимум 90,00 ₽" in text


def test_format_stats_text_without_history() -> None:
    text = format_stats_text(make_subscription(subscription_id=5), None, [])

    assert "нет актуальных офферов" in text
    assert "История цен пока пуста" in text
