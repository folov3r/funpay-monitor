"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.alerts import AlertService
from app.services.monitoring import MonitoringService


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def get_monitoring(request: Request) -> MonitoringService:
    return request.app.state.monitoring


def get_alerts(request: Request) -> AlertService:
    return request.app.state.alerts


def get_local_user_vk_id(request: Request) -> int:
    return int(request.app.state.local_user_vk_id)
