from typing import cast

from app.bot.bot import create_bot
from app.bot.states import AddSubscriptionStates
from app.parsers.base import BaseParser, ParsedCategory
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FakeParser(BaseParser):
    async def fetch_category(self, url_path: str) -> ParsedCategory:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


def make_bot():
    session_factory = cast(async_sessionmaker[AsyncSession], object())
    return create_bot(
        token="test-token",
        session_factory=session_factory,
        parser=FakeParser(),
    )


def test_create_bot_registers_all_handlers() -> None:
    bot = make_bot()
    names = {
        handler.handler.__name__
        for handler in bot.labeler.message_view.handlers
        if hasattr(handler, "handler")
    }

    assert {
        "start_handler",
        "help_handler",
        "add_handler",
        "link_handler",
        "cancel_handler",
        "list_handler",
        "stats_handler",
        "unsubscribe_handler",
        "waiting_link_handler",
        "waiting_server_handler",
        "waiting_mode_handler",
        "waiting_threshold_handler",
        "waiting_confirm_handler",
        "admin_status_handler",
        "admin_reparse_handler",
        "fallback_handler",
    } <= names


def test_create_bot_registers_user_middleware() -> None:
    bot = make_bot()

    assert len(bot.labeler.message_view.middlewares) == 1
    assert bot.labeler.message_view.middlewares[0].__name__ == "UserMiddleware"


def test_admin_handlers_run_before_link_handler() -> None:
    bot = make_bot()
    names = [
        handler.handler.__name__
        for handler in bot.labeler.message_view.handlers
        if hasattr(handler, "handler")
    ]

    assert names.index("admin_reparse_handler") < names.index("link_handler")


def test_add_states_are_distinct() -> None:
    states = {
        AddSubscriptionStates.WAITING_LINK,
        AddSubscriptionStates.WAITING_SERVER,
        AddSubscriptionStates.WAITING_MODE,
        AddSubscriptionStates.WAITING_THRESHOLD,
        AddSubscriptionStates.WAITING_CONFIRM,
    }

    assert len(states) == 5
    assert str(AddSubscriptionStates.WAITING_LINK) == ("AddSubscriptionStates:waiting_link")
