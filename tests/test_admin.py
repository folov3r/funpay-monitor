from datetime import UTC, datetime

from app.bot.admin import (
    format_status_text,
    is_reparse_command,
    is_status_command,
)
from app.db.repositories import AdminStats, ParseRunStatus


def test_admin_command_predicates() -> None:
    assert is_status_command("/status")
    assert is_status_command("Статус")
    assert is_reparse_command("/reparse 3")
    assert is_reparse_command("Перепарсить /chips/30/")
    assert not is_status_command("/start")
    assert not is_reparse_command("/add")


def test_format_status_text_with_runs() -> None:
    stats = AdminStats(
        categories=3,
        active_categories=2,
        users=12,
        active_subscriptions=20,
        offers=870,
    )
    runs = [
        ParseRunStatus(
            category_id=1,
            category_title="Серебро",
            category_path="/chips/30/",
            status="ok",
            started_at=datetime(2026, 1, 10, 12, 30, tzinfo=UTC),
            finished_at=datetime(2026, 1, 10, 12, 31, tzinfo=UTC),
            offers_found=292,
            error_text=None,
        ),
        ParseRunStatus(
            category_id=2,
            category_title="Лоты",
            category_path="/lots/13/",
            status="error",
            started_at=datetime(2026, 1, 10, 12, 0, tzinfo=UTC),
            finished_at=None,
            offers_found=0,
            error_text="timeout",
        ),
    ]

    text = format_status_text(stats, runs)

    assert "Категорий: 3 (активных 2)" in text
    assert "Пользователей: 12" in text
    assert "Активных подписок: 20" in text
    assert "Офферов в базе: 870" in text
    assert "/chips/30/ · 10.01 12:30 · ok · 292 офферов" in text
    assert "/lots/13/ · 10.01 12:00 · error · 0 офферов\n   timeout" in text


def test_format_status_text_without_runs() -> None:
    stats = AdminStats(
        categories=0,
        active_categories=0,
        users=0,
        active_subscriptions=0,
        offers=0,
    )

    assert "Запусков парсера ещё не было." in format_status_text(stats, [])
