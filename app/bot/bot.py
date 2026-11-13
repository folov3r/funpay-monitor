"""Assemble the vkbottle application from handlers and middlewares."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vkbottle.bot import Bot

from app.bot.admin import register_admin_handlers
from app.bot.common import register_common_handlers, register_fallback_handler
from app.bot.middlewares import user_middleware
from app.bot.subscriptions import BotServices, register_subscription_handlers
from app.parsers.base import BaseParser
from app.services.alert_notifier import VkAlertNotifier
from app.services.alerts import AlertService
from app.services.monitoring import MonitoringService


def create_bot(
    *,
    token: str,
    session_factory: async_sessionmaker[AsyncSession],
    parser: BaseParser,
    history_days: int = 7,
    admin_vk_ids: frozenset[int] = frozenset(),
    alert_cooldown_hours: int = 6,
) -> Bot:
    """Create a bot with all handlers registered.

    No network calls happen here, which keeps the function safe for tests and
    lets the caller decide when to start Long Poll.
    """
    bot = Bot(token=token)
    bot.labeler.message_view.register_middleware(user_middleware(session_factory))

    services = BotServices(
        session_factory=session_factory,
        monitoring=MonitoringService(parser, session_factory),
        history_days=history_days,
        admin_vk_ids=admin_vk_ids,
        alerts=AlertService(
            session_factory,
            VkAlertNotifier(bot.api),
            cooldown_hours=alert_cooldown_hours,
        ),
    )

    register_common_handlers(bot)
    register_admin_handlers(bot, services)
    register_subscription_handlers(bot, services)
    register_fallback_handler(bot)
    return bot
