"""The /add confirm step deletes the dialog chain only after a successful save."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.bot.cleanup import ChatCleaner
from app.bot.subscriptions import BotServices, _import_category, register_subscription_handlers
from app.db.repositories import PriceSummary
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

    async def fake_delete(api: Any, peer_id: int, cmids: list[int]) -> list[SimpleNamespace]:
        deleted.append(cmids)
        return [SimpleNamespace(conversation_message_id=cmid, error=None) for cmid in cmids]

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

    async def fake_delete(api: Any, peer_id: int, cmids: list[int]) -> list[SimpleNamespace]:
        deleted.append(cmids)
        return [SimpleNamespace(conversation_message_id=cmid, error=None) for cmid in cmids]

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


def make_import_services(imported: SimpleNamespace) -> BotServices:
    async def fake_import(url_path: str) -> SimpleNamespace:
        return imported

    return BotServices(
        session_factory=cast(Any, fake_session_factory),
        monitoring=cast(Any, SimpleNamespace(import_category=fake_import)),
    )


def patch_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_summary(*args: Any, **kwargs: Any) -> PriceSummary:
        return PriceSummary(Decimal("0.62"), Decimal("1.22"), 603)

    async def fake_offers(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(price=Decimal("0.62"), seller_name="ddegradationn", is_online=False)
        ]

    async def fake_servers(*args: Any, **kwargs: Any) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(id=1, name="Game Pass (5 дней)", funpay_server_id=2356),
        ]

    monkeypatch.setattr("app.bot.subscriptions.current_price_summary", fake_summary)
    monkeypatch.setattr("app.bot.subscriptions.cheapest_offers", fake_offers)
    monkeypatch.setattr("app.bot.subscriptions.list_servers", fake_servers)


async def test_chips_category_shows_summary_before_the_server_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_summary(monkeypatch)
    imported = SimpleNamespace(
        category_id=2,
        title="Робуксы Roblox",
        url_path="/chips/99/",
        offers_found=606,
        item_types=(),
        server_label="Способ передачи",
    )
    services = make_import_services(imported)
    bot = make_bot(services)

    message = FakeMessage(text="/add https://funpay.com/chips/99/")
    await _import_category(bot, message, services, "/chips/99/")

    texts = [text for text, _ in message.sent]
    summary_index = next(index for index, text in enumerate(texts) if "Все предложения" in text)
    server_index = next(
        index for index, text in enumerate(texts) if "Выберите способ передачи" in text
    )
    assert summary_index < server_index
    assert "Медиана: 1,22 ₽" in texts[summary_index]


async def test_lots_category_defers_the_summary_until_the_item_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_summary(monkeypatch)
    imported = SimpleNamespace(
        category_id=1,
        title="Fisch Roblox",
        url_path="/lots/2932/",
        offers_found=3001,
        item_types=("предметы", "услуги"),
        server_label=None,
    )
    services = make_import_services(imported)
    bot = make_bot(services)

    message = FakeMessage(text="/add https://funpay.com/lots/2932/")
    await _import_category(bot, message, services, "/lots/2932/")

    texts = [text for text, _ in message.sent]
    assert not any("Медиана" in text for text in texts)
    assert any("Что отслеживать?" in text for text in texts)
