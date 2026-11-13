"""VK keyboards used by bot handlers."""

from __future__ import annotations

from collections.abc import Sequence

from vkbottle import Keyboard, KeyboardButtonColor, Text

from app.bot.texts import ALL_ITEM_TYPES_LABEL, SKIP_QUERY_LABEL

ANY_SERVER_LABEL = "Любой"
CANCEL_LABEL = "Отмена"

MODE_BUTTONS: tuple[tuple[str, str], ...] = (
    ("Ниже порога", "abs"),
    ("Падение в %", "pct"),
    ("Исторический минимум", "lowest"),
)


def main_menu_keyboard() -> Keyboard:
    return (
        Keyboard(one_time=False, inline=False)
        .add(Text("Добавить"), color=KeyboardButtonColor.PRIMARY)
        .add(Text("Мои подписки"))
        .row()
        .add(Text("Помощь"))
    )


def servers_keyboard(server_names: Sequence[str]) -> Keyboard:
    """Inline keyboard with up to eight servers plus «Любой» and «Отмена»."""
    keyboard = Keyboard(one_time=False, inline=True)
    visible = list(server_names)[:8]
    for index, name in enumerate(visible):
        keyboard.add(Text(name))
        if index % 2 == 1:
            keyboard.row()

    if len(visible) % 2 == 1:
        keyboard.row()
    keyboard.add(Text(ANY_SERVER_LABEL), color=KeyboardButtonColor.PRIMARY)
    keyboard.add(Text(CANCEL_LABEL), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def item_types_keyboard(labels: Sequence[str]) -> Keyboard:
    """Inline keyboard with «Все» and every offer type found on the page."""
    keyboard = Keyboard(one_time=False, inline=True)
    keyboard.add(Text(ALL_ITEM_TYPES_LABEL), color=KeyboardButtonColor.PRIMARY)
    for index, label in enumerate(labels):
        keyboard.add(Text(label))
        if index % 2 == 1:
            keyboard.row()
    if len(labels) % 2 == 1:
        keyboard.row()
    keyboard.add(Text(CANCEL_LABEL), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def query_keyboard() -> Keyboard:
    return (
        Keyboard(one_time=False, inline=True)
        .add(Text(SKIP_QUERY_LABEL), color=KeyboardButtonColor.PRIMARY)
        .add(Text(CANCEL_LABEL), color=KeyboardButtonColor.NEGATIVE)
    )


def cancel_keyboard() -> Keyboard:
    return Keyboard(one_time=False, inline=True).add(
        Text(CANCEL_LABEL), color=KeyboardButtonColor.NEGATIVE
    )


def confirm_keyboard() -> Keyboard:
    return (
        Keyboard(one_time=False, inline=True)
        .add(Text("Сохранить"), color=KeyboardButtonColor.POSITIVE)
        .add(Text(CANCEL_LABEL), color=KeyboardButtonColor.NEGATIVE)
    )


def modes_keyboard() -> Keyboard:
    keyboard = Keyboard(one_time=False, inline=True)
    for label, _ in MODE_BUTTONS:
        keyboard.add(Text(label), color=KeyboardButtonColor.PRIMARY)
        keyboard.row()
    keyboard.add(Text(CANCEL_LABEL), color=KeyboardButtonColor.NEGATIVE)
    return keyboard


def subscriptions_keyboard(subscription_ids: Sequence[int]) -> Keyboard | None:
    """Inline buttons for stats and deletion, up to four subscriptions."""
    ids = list(subscription_ids)[:4]
    if not ids:
        return None

    keyboard = Keyboard(one_time=False, inline=True)
    for index, subscription_id in enumerate(ids):
        keyboard.add(Text(f"Статистика #{subscription_id}"))
        keyboard.add(
            Text(f"Удалить #{subscription_id}"),
            color=KeyboardButtonColor.NEGATIVE,
        )
        if index < len(ids) - 1:
            keyboard.row()
    return keyboard
