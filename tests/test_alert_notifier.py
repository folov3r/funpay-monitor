from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.services import alert_notifier
from app.services.alert_notifier import VkAlertNotifier
from app.services.alerts import PendingAlert


class FakeMessages:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def send(self, **kwargs: object) -> list[SimpleNamespace]:
        self.calls.append(kwargs)
        return [SimpleNamespace(message_id=1)]


class FakeApi:
    def __init__(self) -> None:
        self.messages = FakeMessages()


def make_alert() -> PendingAlert:
    return PendingAlert(
        subscription_id=1,
        user_vk_id=777,
        category_id=10,
        category_title="Серебро",
        server_id=None,
        server_name="любой сервер",
        mode="abs",
        threshold=Decimal("100"),
        price=Decimal("90"),
        previous_price=None,
        historical_min=None,
        snapshot_id=5,
    )


async def test_notifier_sends_text_without_chart() -> None:
    api = FakeApi()

    await VkAlertNotifier(api).send(make_alert())

    call = api.messages.calls[0]
    assert call["peer_id"] == 777
    assert "Цена упала до 90,00 ₽" in call["message"]
    assert call["attachment"] is None
    assert 0 < call["random_id"] < 2**31


async def test_notifier_attaches_chart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()

    async def fake_upload(
        api: object,
        peer_id: int,
        image: bytes,
        **kwargs: object,
    ) -> str:
        assert image == b"png"
        return "photo-1_2"

    monkeypatch.setattr(alert_notifier, "upload_message_photo", fake_upload)

    await VkAlertNotifier(api).send(make_alert(), chart=b"png")

    assert api.messages.calls[0]["attachment"] == "photo-1_2"


async def test_notifier_falls_back_to_text_when_upload_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi()

    async def fake_upload(*args: object, **kwargs: object) -> str:
        raise RuntimeError("upload failed")

    monkeypatch.setattr(alert_notifier, "upload_message_photo", fake_upload)

    await VkAlertNotifier(api).send(make_alert(), chart=b"png")

    assert api.messages.calls[0]["attachment"] is None
