"""The /add confirm step deletes the dialog chain only after a successful save."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.bot.cleanup import ChatCleaner
from app.bot.subscriptions import BotServices, register_subscription_handlers
from vkbottle.bot import Bot


class FakeMessage:
    """Only the attributes used by the /add handlers."""

    def __init__(
        self,
        *,
        peer_id: int = 777,
        conversation_message_id: int = 105,
        text: str = "Сохранить",
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.peer_id = peer_id
        self.conversation_message_id = conversation_message_id
        self.text = text
        self.state_peer = SimpleNamespace(payload=payload or {})
        self.sent: list[tuple[str, int]] = []
        self._next_cmid = conversation_message_id + 1

    async def answer(self, text: str, **kwargs: Any) -> SimpleNamespace:
        cmid = self._next_cmid
        self._next_cmid += 1
        self.sent.append((text, cmid))
        return SimpleNamespace(conversation_message_id=cmid)


class FakeSession:
    async def __aenter__(self) -> FakeSession:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def commit(self) -> None:
        return None


def fake_session_factory() -> FakeSession:
    return FakeSession()


def make_services(cleaner: ChatCleaner | None = None) -> BotServices:
    return BotServices(
        session_factory=cast(Any, fake_session_factory),
        monitoring=cast(Any, object()),
        cleaner=cleaner or ChatCleaner(),
    )


def make_bot(services: BotServices) -> Bot:
    bot = Bot(token="test-token")
    register_subscription_handlers(bot, services)
    return bot


def confirm_handler(bot: Bot) -> Any:
    return next(
        handler.handler
        for handler in bot.labeler.message_view.handlers
        if getattr(handler.handler, "__name__", "") == "waiting_confirm_handler"
    )


CONFIRM_PAYLOAD = {
    "category_id": 1,
    "mode": "abs",
    "threshold": "100",
    "server_id": None,
    "server_name": "любой",
    "item_type": "предметы",
    "query": "cosmic relic",
}


async def test_confirm_deletes_dialog_but_keeps_the_final_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_upsert(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(id=42)

    monkeypatch.setattr("app.bot.subscriptions.upsert_subscription", fake_upsert)

    deleted: list[list[int]] = []

    async def fake_delete(api: Any, peer_id: int, cmids: list[int]) -> None:
        deleted.append(cmids)

    cleaner = ChatCleaner()
    cleaner.track(777, [100, 101, 102, 103, 104])
    services = make_services(cleaner)
    monkeypatch.setattr(cleaner, "_delete", fake_delete)
    bot = make_bot(services)

    message = FakeMessage(payload=CONFIRM_PAYLOAD)
    await confirm_handler(bot)(message, user_id=1)

    assert deleted == [[100, 101, 102, 103, 104, 105]]
    assert message.sent == [
        (
            "Подписка #42 сохранена. Как только воркер соберёт свежие цены, бот проверит условие.",
            106,
        )
    ]
    assert cleaner.tracked(777) == []


async def test_confirm_keeps_the_dialog_when_saving_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_upsert(*args: Any, **kwargs: Any) -> SimpleNamespace:
        raise RuntimeError("database is down")

    monkeypatch.setattr("app.bot.subscriptions.upsert_subscription", failing_upsert)

    deleted: list[list[int]] = []

    async def fake_delete(api: Any, peer_id: int, cmids: list[int]) -> None:
        deleted.append(cmids)

    cleaner = ChatCleaner()
    cleaner.track(777, [100, 101, 102, 103, 104])
    services = make_services(cleaner)
    monkeypatch.setattr(cleaner, "_delete", fake_delete)
    bot = make_bot(services)

    message = FakeMessage(payload=CONFIRM_PAYLOAD)
    with pytest.raises(RuntimeError):
        await confirm_handler(bot)(message, user_id=1)

    assert deleted == []
    assert cleaner.tracked(777) == [100, 101, 102, 103, 104, 105]
