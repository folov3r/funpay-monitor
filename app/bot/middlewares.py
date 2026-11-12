"""Middlewares shared by bot handlers."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vkbottle import BaseMiddleware
from vkbottle.bot import Message

from app.db.repositories import get_or_create_user

logger = logging.getLogger(__name__)


def user_middleware(
    session_factory: async_sessionmaker[AsyncSession],
) -> type[BaseMiddleware[Message]]:
    """Build a middleware that upserts the sender and exposes ``user_id``."""

    class UserMiddleware(BaseMiddleware[Message]):
        async def pre(self) -> None:
            vk_id: int | None = self.event.from_id
            if vk_id is None or vk_id <= 0:
                self.stop("bot works only with private user messages")

            async with session_factory() as session:
                user = await get_or_create_user(session, vk_id)
                await session.commit()
                user_id = user.id

            context: dict[str, Any] = {"user_id": user_id, "vk_id": vk_id}
            self.send(context)

    return UserMiddleware
