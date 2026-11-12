"""Parse categories, persist offers/snapshots and record parse runs."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Category, ParseRun
from app.db.repositories import (
    PARSE_RUN_ERROR,
    PARSE_RUN_OK,
    add_price_snapshots,
    finish_parse_run,
    get_or_create_category,
    list_active_categories,
    replace_offers,
    start_parse_run,
    upsert_servers,
)
from app.parsers.base import BaseParser, ParsedCategory

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CategoryRef:
    """Lightweight category reference that survives a closed DB session."""

    id: int
    title: str
    url_path: str


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    """Result of one category parse run."""

    category_id: int
    title: str
    status: str
    offers_found: int
    snapshots_created: int
    error_text: str | None = None


class MonitoringService:
    """Run the parse → persist → snapshot pipeline for tracked categories."""

    def __init__(
        self,
        parser: BaseParser,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._parser = parser
        self._session_factory = session_factory

    async def run_all_active(self) -> list[ParseOutcome]:
        """Parse every active category sequentially, respecting the HTTP throttle."""
        async with self._session_factory() as session:
            categories = await list_active_categories(session)
            refs = [
                CategoryRef(id=category.id, title=category.title, url_path=category.url_path)
                for category in categories
            ]

        outcomes: list[ParseOutcome] = []
        for ref in refs:
            outcomes.append(await self.run_category(ref))
        return outcomes

    async def run_category_by_id(self, category_id: int) -> ParseOutcome | None:
        """Run one category by database id (used by admin /reparse)."""
        async with self._session_factory() as session:
            category = await session.get(Category, category_id)
            if category is None:
                return None
            ref = CategoryRef(
                id=category.id,
                title=category.title,
                url_path=category.url_path,
            )

        return await self.run_category(ref)

    async def run_category(self, category: CategoryRef) -> ParseOutcome:
        """Parse one category and persist the result or the failure."""
        try:
            run_id = await self._start_run(category.id)
        except Exception as exc:  # pragma: no cover - database outage
            logger.exception("Could not start parse run for %s", category.url_path)
            return ParseOutcome(
                category_id=category.id,
                title=category.title,
                status=PARSE_RUN_ERROR,
                offers_found=0,
                snapshots_created=0,
                error_text=str(exc),
            )

        try:
            parsed = await self._parser.fetch_category(category.url_path)
        except Exception as exc:
            logger.exception("Parsing failed for %s", category.url_path)
            await self._record_failure(run_id, 0, exc)
            return ParseOutcome(
                category_id=category.id,
                title=category.title,
                status=PARSE_RUN_ERROR,
                offers_found=0,
                snapshots_created=0,
                error_text=str(exc),
            )

        try:
            snapshots_created, status, error_text = await self._persist(parsed, run_id)
        except Exception as exc:
            logger.exception("Saving parsed data failed for %s", category.url_path)
            await self._record_failure(run_id, len(parsed.offers), exc)
            return ParseOutcome(
                category_id=category.id,
                title=category.title,
                status=PARSE_RUN_ERROR,
                offers_found=len(parsed.offers),
                snapshots_created=0,
                error_text=str(exc),
            )

        logger.info(
            "Parsed %s: %s offers, %s snapshots, status=%s",
            category.url_path,
            len(parsed.offers),
            snapshots_created,
            status,
        )
        return ParseOutcome(
            category_id=category.id,
            title=category.title,
            status=status,
            offers_found=len(parsed.offers),
            snapshots_created=snapshots_created,
            error_text=error_text,
        )

    async def _start_run(self, category_id: int) -> int:
        async with self._session_factory() as session:
            run = await start_parse_run(session, category_id)
            await session.commit()
            return run.id

    async def _record_failure(self, run_id: int, offers_found: int, error: Exception) -> None:
        try:
            async with self._session_factory() as session:
                run = await session.get(ParseRun, run_id)
                if run is None:
                    return
                await finish_parse_run(
                    session,
                    run,
                    status=PARSE_RUN_ERROR,
                    offers_found=offers_found,
                    error_text=str(error),
                )
                await session.commit()
        except Exception:  # pragma: no cover - database outage during error handling
            logger.exception("Could not record failure for parse run %s", run_id)

    async def _persist(
        self,
        parsed: ParsedCategory,
        run_id: int,
    ) -> tuple[int, str, str | None]:
        status = PARSE_RUN_OK if parsed.offers else PARSE_RUN_ERROR
        error_text = (
            None if parsed.offers else "no offers found (possible markup change or bot protection)"
        )

        async with self._session_factory() as session:
            run = await session.get(ParseRun, run_id)
            if run is None:
                raise RuntimeError(f"parse run {run_id} disappeared")

            category = await get_or_create_category(session, parsed.category)
            servers = await upsert_servers(session, category.id, parsed.offers)
            await replace_offers(session, category.id, parsed.offers, servers)
            snapshots = await add_price_snapshots(session, category.id, parsed.offers, servers)
            category.last_parsed_at = datetime.now(UTC)
            await finish_parse_run(
                session,
                run,
                status=status,
                offers_found=len(parsed.offers),
                error_text=error_text,
            )
            await session.commit()

        return len(snapshots), status, error_text
