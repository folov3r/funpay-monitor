"""Background worker: parses active categories on a schedule."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from vkbottle.bot import Bot

from app.config import get_settings
from app.db.base import build_engine, build_session_factory
from app.db.repositories import PARSE_RUN_OK, fail_stale_parse_runs
from app.logging import setup_logging
from app.parsers.funpay import FunPayParser
from app.services.alert_notifier import VkAlertNotifier
from app.services.alerts import AlertService
from app.services.monitoring import MonitoringService, ParseOutcome

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    logger.info("FunPay Monitor worker is starting")
    logger.info("Parse interval: %s min", settings.parse_interval_minutes)

    engine = build_engine()
    session_factory = build_session_factory(engine)
    parser = FunPayParser()
    monitoring = MonitoringService(parser, session_factory)

    async with session_factory() as session:
        stale = await fail_stale_parse_runs(
            session,
            older_than=datetime.now(UTC) - timedelta(hours=1),
        )
        await session.commit()
    if stale:
        logger.warning("Marked %s stale parse runs as failed", stale)

    bot: Bot | None = None
    alerts: AlertService | None = None
    if settings.vk_group_token:
        bot = Bot(token=settings.vk_group_token)
        alerts = AlertService(
            session_factory,
            VkAlertNotifier(bot.api),
            cooldown_hours=settings.alert_cooldown_hours,
        )
    else:
        logger.warning("VK_GROUP_TOKEN is empty: parsing continues, alerts are disabled")

    async def on_outcome(outcome: ParseOutcome) -> None:
        if alerts is None or outcome.status != PARSE_RUN_OK:
            return
        try:
            sent = await alerts.process_category(outcome.category_id)
        except Exception:
            logger.exception("Alert processing failed for %s", outcome.title)
            return
        if sent:
            logger.info("Sent %s alerts for %s", len(sent), outcome.title)

    async def parse_job() -> None:
        logger.info("Scheduled parse run started")
        try:
            outcomes = await monitoring.run_all_active(on_outcome)
        except Exception:
            logger.exception("Parse run failed before finishing")
            return

        ok_count = sum(1 for outcome in outcomes if outcome.status == PARSE_RUN_OK)
        failed_count = len(outcomes) - ok_count
        logger.info(
            "Parse run finished: %s categories, %s ok, %s failed",
            len(outcomes),
            ok_count,
            failed_count,
        )

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        parse_job,
        "interval",
        minutes=settings.parse_interval_minutes,
        jitter=120,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
        id="parse-all-categories",
    )
    scheduler.start()
    logger.info("Scheduler started, first run is immediate")

    stop_event = asyncio.Event()

    def request_stop(*_: object) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, request_stop)

    try:
        await stop_event.wait()
    finally:
        scheduler.shutdown(wait=False)
        await parser.aclose()
        if bot is not None:
            await bot.api.http_client.close()
        await engine.dispose()
        logger.info("Worker stopped")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
