"""Entry point of the background worker process.

Placeholder for now: APScheduler, the parsing pipeline and alert delivery are
the week 2-3 milestones.
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

    logger.info("FunPay Monitor worker is starting")
    logger.info("Parse interval: %s min", settings.parse_interval_minutes)

    stop_event = asyncio.Event()

    def request_stop(*_: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_stop)

    await stop_event.wait()
    logger.info("Worker stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
