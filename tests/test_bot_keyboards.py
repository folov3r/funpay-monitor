import json

from app.bot.keyboards import (
    cancel_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
    modes_keyboard,
    servers_keyboard,
    subscriptions_keyboard,
)
from vkbottle import Keyboard


def labels(keyboard: Keyboard) -> list[str]:
    payload = json.loads(keyboard.get_json())
    return [button["action"]["label"] for row in payload["buttons"] for button in row]


def test_main_menu_keyboard() -> None:
    assert labels(main_menu_keyboard()) == ["Добавить", "Мои подписки", "Помощь"]


def test_servers_keyboard_contains_servers_and_any() -> None:
    keyboard = servers_keyboard(["EU", "NA", "Asia"])

    assert labels(keyboard) == ["EU", "NA", "Asia", "Любой", "Отмена"]


def test_servers_keyboard_limits_to_eight_servers() -> None:
    keyboard = servers_keyboard([f"server-{index}" for index in range(12)])

    assert labels(keyboard) == [
        *[f"server-{index}" for index in range(8)],
        "Любой",
        "Отмена",
    ]


def test_modes_keyboard() -> None:
    assert labels(modes_keyboard()) == [
        "Ниже порога",
        "Падение в %",
        "Исторический минимум",
        "Отмена",
    ]


def test_cancel_and_confirm_keyboards() -> None:
    assert labels(cancel_keyboard()) == ["Отмена"]
    assert labels(confirm_keyboard()) == ["Сохранить", "Отмена"]


def test_subscriptions_keyboard_is_none_for_empty_list() -> None:
    assert subscriptions_keyboard([]) is None


def test_subscriptions_keyboard_has_actions() -> None:
    keyboard = subscriptions_keyboard([3, 7])

    assert keyboard is not None
    assert labels(keyboard) == [
        "Статистика #3",
        "Удалить #3",
        "Статистика #7",
        "Удалить #7",
    ]
