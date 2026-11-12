"""Entry point of the VK bot process.

Placeholder for now: the vkbottle application (Long Poll, command handlers,
inline keyboards) is the week 2 milestone.
"""

import asyncio
import contextlib
import logging
import signal

from app.config import get_settings
from app.logging import setup_logging

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info("FunPay Monitor bot is starting")
    if not settings.vk_group_token:
        logger.warning(
            "VK_GROUP_TOKEN is empty: set it in .env to connect the bot to VK. "
            "Until then the process stays idle."
        )

    stop_event = asyncio.Event()

    def request_stop(*_: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_stop)

    await stop_event.wait()
    logger.info("Bot stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
