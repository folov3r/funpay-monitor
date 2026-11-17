"""FastAPI application shared by the Tauri window and the local web UI."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.notifier import DesktopAlertNotifier
from app.api.routes import router
from app.config import get_settings
from app.db.base import build_engine, build_session_factory, ensure_schema
from app.db.repositories import PARSE_RUN_OK, fail_stale_parse_runs
from app.parsers.base import BaseParser
from app.parsers.funpay import FunPayParser
from app.services.alerts import AlertService
from app.services.monitoring import MonitoringService, ParseOutcome

logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _package_version() -> str:
    try:
        return version("funpay-monitor")
    except PackageNotFoundError:  # pragma: no cover - source checkout without install
        return "0.0.0"


def create_app(
    *,
    database_url: str | None = None,
    enable_scheduler: bool | None = None,
    parser: BaseParser | None = None,
) -> FastAPI:
    """Build the local API.

    ``parser`` and ``enable_scheduler`` are injectable so tests can run without
    network access and without a background job.
    """
    settings = get_settings()
    url = database_url or settings.database_url
    scheduler_enabled = settings.scheduler_enabled if enable_scheduler is None else enable_scheduler

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(url)
        await ensure_schema(engine)
        session_factory = build_session_factory(engine)
        funpay_parser = parser or FunPayParser()

        async with session_factory() as session:
            stale = await fail_stale_parse_runs(
                session,
                older_than=datetime.now(UTC) - timedelta(hours=1),
            )
            await session.commit()
        if stale:
            logger.warning("Marked %s stale parse runs as failed", stale)

        monitoring = MonitoringService(funpay_parser, session_factory)
        alerts = AlertService(
            session_factory,
            DesktopAlertNotifier(),
            cooldown_hours=settings.alert_cooldown_hours,
            history_days=settings.history_days,
        )

        async def on_outcome(outcome: ParseOutcome) -> None:
            if outcome.status != PARSE_RUN_OK:
                return
            try:
                await alerts.process_category(outcome.category_id)
            except Exception:
                logger.exception("Alert processing failed for %s", outcome.title)

        async def parse_job() -> None:
            logger.info("Scheduled parse run started")
            try:
                outcomes = await monitoring.run_all_active(on_outcome)
            except Exception:
                logger.exception("Parse run failed before finishing")
                return
            ok_count = sum(1 for outcome in outcomes if outcome.status == PARSE_RUN_OK)
            logger.info(
                "Parse run finished: %s categories, %s ok, %s failed",
                len(outcomes),
                ok_count,
                len(outcomes) - ok_count,
            )

        scheduler: AsyncIOScheduler | None = None
        if scheduler_enabled:
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

        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.monitoring = monitoring
        app.state.alerts = alerts
        app.state.parser = funpay_parser
        app.state.scheduler = scheduler
        app.state.settings = settings
        app.state.version = _package_version()
        app.state.database_backend = engine.url.get_backend_name()
        app.state.local_user_vk_id = settings.local_user_vk_id

        try:
            yield
        finally:
            if scheduler is not None:
                scheduler.shutdown(wait=False)
            await funpay_parser.aclose()
            await engine.dispose()
            logger.info("API stopped")

    app = FastAPI(
        title="FunPay Monitor",
        version=_package_version(),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?|tauri://localhost",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)

    if FRONTEND_DIST.is_dir():
        app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")

    return app


app = create_app()
