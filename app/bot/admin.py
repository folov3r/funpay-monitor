"""Admin-only commands: /status and /reparse."""

from __future__ import annotations

import logging
from datetime import UTC

from vkbottle.bot import Bot, Message

from app.bot.subscriptions import BotServices, _reset_state
from app.bot.texts import extract_category_path, split_command
from app.db.repositories import (
    AdminStats,
    ParseRunStatus,
    get_admin_stats,
    list_recent_parse_runs,
)

logger = logging.getLogger(__name__)

STATUS_COMMANDS = {"/status", "статус"}
REPARSE_COMMANDS = {"/reparse", "перепарсить"}


def is_status_command(text: str | None) -> bool:
    return split_command(text)[0] in STATUS_COMMANDS


def is_reparse_command(text: str | None) -> bool:
    return split_command(text)[0] in REPARSE_COMMANDS


def format_status_text(
    stats: AdminStats,
    runs: list[ParseRunStatus],
) -> str:
    """Build the admin dashboard text."""
    lines = [
        "Статус FunPay Monitor",
        "",
        f"Категорий: {stats.categories} (активных {stats.active_categories})",
        f"Пользователей: {stats.users}",
        f"Активных подписок: {stats.active_subscriptions}",
        f"Офферов в базе: {stats.offers}",
    ]
    if not runs:
        lines.extend(["", "Запусков парсера ещё не было."])
        return "\n".join(lines)

    lines.extend(["", "Последние запуски:"])
    for run in runs:
        moment = run.started_at.astimezone(UTC).strftime("%d.%m %H:%M")
        line = f"{run.category_path} · {moment} · {run.status} · {run.offers_found} офферов"
        if run.error_text:
            line = f"{line}\n   {run.error_text[:120]}"
        lines.append(line)
    return "\n".join(lines)


def register_admin_handlers(bot: Bot, services: BotServices) -> None:
    """Register /status and /reparse, visible only to configured admins."""

    async def deny(message: Message, vk_id: int) -> None:
        logger.warning("Non-admin %s tried an admin command", vk_id)
        await message.answer("Команда доступна только администратору.")

    @bot.on.message(func=lambda message: is_status_command(message.text))
    async def admin_status_handler(message: Message, user_id: int, vk_id: int) -> None:
        if not services.is_admin(vk_id):
            await deny(message, vk_id)
            return

        await _reset_state(bot, message)
        async with services.session_factory() as session:
            stats = await get_admin_stats(session)
            runs = await list_recent_parse_runs(session, limit=5)
        await message.answer(format_status_text(stats, runs))

    @bot.on.message(func=lambda message: is_reparse_command(message.text))
    async def admin_reparse_handler(message: Message, user_id: int, vk_id: int) -> None:
        if not services.is_admin(vk_id):
            await deny(message, vk_id)
            return

        await _reset_state(bot, message)
        _, argument = split_command(message.text)
        path = extract_category_path(argument)
        if path is not None:
            await _reparse_path(message, services, path)
            return

        raw = argument.strip().lstrip("#")
        if not raw.isdigit():
            await message.answer(
                "Укажите id категории или ссылку: /reparse 3 или /reparse /chips/30/"
            )
            return
        await _reparse_id(message, services, int(raw))


async def _reparse_id(message: Message, services: BotServices, category_id: int) -> None:
    await message.answer("Запускаю парсинг категории…")
    try:
        outcome = await services.monitoring.run_category_by_id(category_id)
    except Exception:
        logger.exception("Admin reparse failed for category %s", category_id)
        await message.answer("Парсинг не удался, подробности в логах воркера.")
        return

    if outcome is None:
        await message.answer(f"Категория #{category_id} не найдена.")
        return
    if outcome.status == "ok":
        await message.answer(
            f"«{outcome.title}»: {outcome.offers_found} офферов, "
            f"{outcome.snapshots_created} снапшотов."
        )
    else:
        await message.answer(
            f"«{outcome.title}»: ошибка парсинга. {outcome.error_text or 'без подробностей'}"
        )
    await _notify_alerts(message, services, outcome.category_id)


async def _reparse_path(message: Message, services: BotServices, path: str) -> None:
    await message.answer("Загружаю категорию с FunPay…")
    try:
        imported = await services.monitoring.import_category(path)
    except Exception:
        logger.exception("Admin import failed for %s", path)
        await message.answer("Не удалось загрузить страницу FunPay, подробности в логах.")
        return

    await message.answer(
        f"«{imported.title}»: {imported.offers_found} офферов, "
        f"{imported.snapshots_created} снапшотов."
    )
    await _notify_alerts(message, services, imported.category_id)


async def _notify_alerts(message: Message, services: BotServices, category_id: int) -> None:
    if services.alerts is None:
        return
    try:
        sent = await services.alerts.process_category(category_id)
    except Exception:
        logger.exception("Alert evaluation failed after admin reparse")
        await message.answer("Парсинг завершён, но проверка алертов упала — смотрите логи.")
        return
    if sent:
        await message.answer(f"Сработало алертов: {len(sent)}.")
