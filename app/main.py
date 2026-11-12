"""Entry point of the VK bot process (Long Poll)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

from app.bot.bot import create_bot
from app.config import get_settings
from app.db.base import build_engine, build_session_factory
from app.logging import setup_logging
from app.parsers.funpay import FunPayParser

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if not settings.vk_group_token:
        logger.error(
            "VK_GROUP_TOKEN is empty. Set it in .env (community Long Poll token) "
            "and restart the bot."
        )
        return

    logger.info("FunPay Monitor bot is starting")
    engine = build_engine()
    session_factory = build_session_factory(engine)
    parser = FunPayParser()
    bot = create_bot(
        token=settings.vk_group_token,
        session_factory=session_factory,
        parser=parser,
    )

    stop_event = asyncio.Event()

    def request_stop(*_: object) -> None:
        stop_event.set()
        bot.polling.stop()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_stop)

    try:
        await bot.run_polling()
    finally:
        await parser.aclose()
        await engine.dispose()
        logger.info("Bot stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
