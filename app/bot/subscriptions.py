"""Subscription commands and the /add finite-state dialog."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vkbottle.bot import Bot, Message

from app.bot.keyboards import (
    ANY_SERVER_LABEL,
    cancel_keyboard,
    confirm_keyboard,
    main_menu_keyboard,
    modes_keyboard,
    servers_keyboard,
    subscriptions_keyboard,
)
from app.bot.states import AddSubscriptionStates
from app.bot.texts import (
    extract_category_path,
    format_condition,
    format_server_name,
    format_stats_text,
    format_subscription_list,
    is_add_command,
    is_cancel,
    is_list_command,
    is_stats_command,
    is_unsubscribe_command,
    mode_from_label,
    normalize_text,
    parse_subscription_id,
    parse_threshold,
    split_command,
)
from app.db.repositories import (
    current_price_summary,
    deactivate_subscription,
    get_user_subscription,
    list_aggregated_snapshots,
    list_price_snapshots,
    list_servers,
    list_user_subscriptions,
    upsert_subscription,
)
from app.services.charts import ChartPoint, render_price_chart_async
from app.services.monitoring import MonitoringService
from app.services.vk_upload import upload_message_photo

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BotServices:
    """Dependencies used by subscription handlers."""

    session_factory: async_sessionmaker[AsyncSession]
    monitoring: MonitoringService
    history_days: int = 7


def _payload(message: Message) -> dict[str, Any]:
    peer = message.state_peer
    return dict(peer.payload) if peer is not None else {}


def _state_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "state"}


def _server_options(servers: list[Any]) -> list[dict[str, Any]]:
    return [
        {"id": server.id, "name": server.name} for server in servers if server.funpay_server_id != 0
    ]


async def _reset_state(bot: Bot, message: Message) -> None:
    await bot.state_dispenser.delete(message.peer_id)


async def _import_category(
    bot: Bot,
    message: Message,
    services: BotServices,
    url_path: str,
) -> None:
    await message.answer("Проверяю категорию на FunPay, это может занять несколько секунд…")
    try:
        imported = await services.monitoring.import_category(url_path)
    except Exception:
        logger.exception("Could not import category %s", url_path)
        await message.answer(
            "Не удалось загрузить страницу FunPay. Проверьте, что ссылка ведёт "
            "на категорию /chips/… или /lots/…, и попробуйте ещё раз.",
            keyboard=main_menu_keyboard(),
        )
        return

    async with services.session_factory() as session:
        servers = await list_servers(session, imported.category_id)
    options = _server_options(servers)

    if not options:
        payload = {
            "category_id": imported.category_id,
            "category_title": imported.title,
            "url_path": imported.url_path,
            "servers": [],
        }
        await message.answer(
            f"Категория «{imported.title}»: {imported.offers_found} офферов. "
            "Серверы не нашлись, поэтому подписка будет на любой сервер."
        )
        await _ask_mode(bot, message, payload, server_id=None, server_name="любой сервер")
        return

    payload = {
        "category_id": imported.category_id,
        "category_title": imported.title,
        "url_path": imported.url_path,
        "servers": options,
    }
    await bot.state_dispenser.set(
        message.peer_id,
        AddSubscriptionStates.WAITING_SERVER,
        **_state_kwargs(payload),
    )
    names = [option["name"] for option in options]
    await message.answer(
        f"Категория «{imported.title}»: {imported.offers_found} офферов.\n"
        "Выберите сервер (можно прислать название текстом):",
        keyboard=servers_keyboard(names),
    )


async def _ask_mode(
    bot: Bot,
    message: Message,
    payload: dict[str, Any],
    *,
    server_id: int | None,
    server_name: str,
) -> None:
    next_payload = {
        **payload,
        "server_id": server_id,
        "server_name": server_name,
    }
    await bot.state_dispenser.set(
        message.peer_id,
        AddSubscriptionStates.WAITING_MODE,
        **_state_kwargs(next_payload),
    )
    await message.answer(
        "Когда присылать уведомление?",
        keyboard=modes_keyboard(),
    )


async def _ask_confirm(
    bot: Bot,
    message: Message,
    payload: dict[str, Any],
) -> None:
    mode = str(payload.get("mode", "abs"))
    threshold_raw = payload.get("threshold")
    threshold = Decimal(str(threshold_raw)) if threshold_raw is not None else None
    condition = format_condition(mode, threshold)
    server_name = str(payload.get("server_name") or "любой сервер")
    title = str(payload.get("category_title") or "категория")

    await bot.state_dispenser.set(
        message.peer_id,
        AddSubscriptionStates.WAITING_CONFIRM,
        **_state_kwargs(payload),
    )
    await message.answer(
        f"Проверьте подписку:\n\n{title}\nСервер: {server_name}\nУсловие: {condition}",
        keyboard=confirm_keyboard(),
    )


async def _send_subscription_list(
    message: Message,
    services: BotServices,
    user_id: int,
) -> None:
    async with services.session_factory() as session:
        subscriptions = await list_user_subscriptions(session, user_id)
        summaries = {
            subscription.id: await current_price_summary(
                session,
                subscription.category_id,
                subscription.server_id,
            )
            for subscription in subscriptions
        }

    keyboard = subscriptions_keyboard([subscription.id for subscription in subscriptions])
    await message.answer(
        format_subscription_list(subscriptions, summaries),
        keyboard=keyboard or main_menu_keyboard(),
    )


def register_subscription_handlers(bot: Bot, services: BotServices) -> None:
    """Register /add, /list, /stats, /unsubscribe and FSM step handlers."""

    @bot.on.message(func=lambda message: is_add_command(message.text))
    async def add_handler(message: Message, user_id: int) -> None:
        _, argument = split_command(message.text)
        path = extract_category_path(argument)
        if path is None:
            await bot.state_dispenser.set(
                message.peer_id,
                AddSubscriptionStates.WAITING_LINK,
            )
            await message.answer(
                "Пришлите ссылку на категорию FunPay, например https://funpay.com/chips/30/",
                keyboard=cancel_keyboard(),
            )
            return
        await _import_category(bot, message, services, path)

    @bot.on.message(func=lambda message: extract_category_path(message.text) is not None)
    async def link_handler(message: Message, user_id: int) -> None:
        path = extract_category_path(message.text)
        if path is None:  # pragma: no cover - guarded by the rule above
            return
        await _import_category(bot, message, services, path)

    @bot.on.message(func=lambda message: is_cancel(message.text))
    async def cancel_handler(message: Message, user_id: int) -> None:
        await _reset_state(bot, message)
        await message.answer("Отменено.", keyboard=main_menu_keyboard())

    @bot.on.message(func=lambda message: is_list_command(message.text))
    async def list_handler(message: Message, user_id: int) -> None:
        await _reset_state(bot, message)
        await _send_subscription_list(message, services, user_id)

    @bot.on.message(func=lambda message: is_stats_command(message.text))
    async def stats_handler(message: Message, user_id: int) -> None:
        await _reset_state(bot, message)
        _, argument = split_command(message.text)
        subscription_id = parse_subscription_id(argument)
        if subscription_id is None:
            await _send_subscription_list(message, services, user_id)
            return
        await _send_stats(bot, message, services, user_id, subscription_id)

    @bot.on.message(func=lambda message: is_unsubscribe_command(message.text))
    async def unsubscribe_handler(message: Message, user_id: int) -> None:
        await _reset_state(bot, message)
        _, argument = split_command(message.text)
        subscription_id = parse_subscription_id(argument)
        if subscription_id is None:
            await _send_subscription_list(message, services, user_id)
            return

        async with services.session_factory() as session:
            subscription = await deactivate_subscription(session, subscription_id, user_id)
            await session.commit()

        if subscription is None:
            await message.answer(
                f"Подписка #{subscription_id} не найдена.",
                keyboard=main_menu_keyboard(),
            )
            return
        await message.answer(
            f"Подписка #{subscription.id} на «{subscription.category.title}» удалена.",
            keyboard=main_menu_keyboard(),
        )

    @bot.on.message(state=AddSubscriptionStates.WAITING_LINK)
    async def waiting_link_handler(message: Message, user_id: int) -> None:
        path = extract_category_path(message.text)
        if path is None:
            await message.answer(
                "Не вижу ссылку FunPay. Пришлите, например, https://funpay.com/chips/30/",
                keyboard=cancel_keyboard(),
            )
            return
        await _import_category(bot, message, services, path)

    @bot.on.message(state=AddSubscriptionStates.WAITING_SERVER)
    async def waiting_server_handler(message: Message, user_id: int) -> None:
        payload = _payload(message)
        text = normalize_text(message.text)
        options = payload.get("servers") or []

        if text == normalize_text(ANY_SERVER_LABEL):
            await _ask_mode(
                bot,
                message,
                payload,
                server_id=None,
                server_name="любой сервер",
            )
            return

        chosen = next(
            (option for option in options if normalize_text(option["name"]) == text),
            None,
        )
        if chosen is None:
            await message.answer(
                "Выберите сервер кнопкой или пришлите его название.",
                keyboard=servers_keyboard([option["name"] for option in options]),
            )
            return

        await _ask_mode(
            bot,
            message,
            payload,
            server_id=int(chosen["id"]),
            server_name=str(chosen["name"]),
        )

    @bot.on.message(state=AddSubscriptionStates.WAITING_MODE)
    async def waiting_mode_handler(message: Message, user_id: int) -> None:
        mode = mode_from_label(message.text)
        if mode is None:
            await message.answer(
                "Выберите условие кнопкой.",
                keyboard=modes_keyboard(),
            )
            return

        payload = _payload(message)
        if mode == "lowest":
            await _ask_confirm(bot, message, {**payload, "mode": mode, "threshold": None})
            return

        await bot.state_dispenser.set(
            message.peer_id,
            AddSubscriptionStates.WAITING_THRESHOLD,
            **_state_kwargs({**payload, "mode": mode}),
        )
        prompt = (
            "Введите порог в рублях, например 1450 или 1450,50:"
            if mode == "abs"
            else "Введите процент падения, например 5 или 7,5:"
        )
        await message.answer(prompt, keyboard=cancel_keyboard())

    @bot.on.message(state=AddSubscriptionStates.WAITING_THRESHOLD)
    async def waiting_threshold_handler(message: Message, user_id: int) -> None:
        payload = _payload(message)
        mode = str(payload.get("mode", "abs"))
        threshold = parse_threshold(message.text or "", mode)
        if threshold is None:
            hint = (
                "Нужно положительное число до 100."
                if mode == "pct"
                else "Нужно положительное число, например 1450 или 1450,50."
            )
            await message.answer(hint, keyboard=cancel_keyboard())
            return

        await _ask_confirm(
            bot,
            message,
            {**payload, "threshold": str(threshold)},
        )

    @bot.on.message(state=AddSubscriptionStates.WAITING_CONFIRM)
    async def waiting_confirm_handler(message: Message, user_id: int) -> None:
        if normalize_text(message.text) not in {"сохранить", "да", "подтвердить"}:
            await message.answer(
                "Нажмите «Сохранить» или «Отмена».",
                keyboard=confirm_keyboard(),
            )
            return

        payload = _payload(message)
        category_id = payload.get("category_id")
        mode = payload.get("mode")
        if category_id is None or mode not in {"abs", "pct", "lowest"}:
            await _reset_state(bot, message)
            await message.answer(
                "Что-то потерялось в диалоге. Начните заново: /add",
                keyboard=main_menu_keyboard(),
            )
            return

        threshold_raw = payload.get("threshold")
        threshold = Decimal(str(threshold_raw)) if threshold_raw is not None else None

        async with services.session_factory() as session:
            subscription = await upsert_subscription(
                session,
                user_id=user_id,
                category_id=int(category_id),
                server_id=payload.get("server_id"),
                mode=str(mode),
                threshold=threshold,
            )
            await session.commit()
            subscription_id = subscription.id

        await _reset_state(bot, message)
        await message.answer(
            f"Подписка #{subscription_id} сохранена. "
            "Как только воркер соберёт свежие цены, бот проверит условие.",
            keyboard=main_menu_keyboard(),
        )


async def _send_stats(
    bot: Bot,
    message: Message,
    services: BotServices,
    user_id: int,
    subscription_id: int,
) -> None:
    since = datetime.now(UTC) - timedelta(days=services.history_days)

    async with services.session_factory() as session:
        subscription = await get_user_subscription(session, subscription_id, user_id)
        if subscription is None:
            await message.answer(
                f"Подписка #{subscription_id} не найдена.",
                keyboard=main_menu_keyboard(),
            )
            return

        current = await current_price_summary(
            session,
            subscription.category_id,
            subscription.server_id,
        )
        if subscription.server_id is None:
            aggregates = await list_aggregated_snapshots(
                session,
                subscription.category_id,
                since=since,
            )
            points = [
                ChartPoint(
                    captured_at=aggregate.captured_at,
                    min_price=aggregate.min_price,
                    median_price=aggregate.median_price,
                )
                for aggregate in aggregates
            ]
        else:
            snapshots = await list_price_snapshots(
                session,
                subscription.category_id,
                server_id=subscription.server_id,
                since=since,
            )
            points = [
                ChartPoint(
                    captured_at=snapshot.captured_at,
                    min_price=snapshot.min_price,
                    median_price=snapshot.median_price,
                )
                for snapshot in snapshots
            ]

    text = format_stats_text(
        subscription,
        current,
        points,
        days=services.history_days,
    )
    if not points:
        await message.answer(text, keyboard=main_menu_keyboard())
        return

    image = await render_price_chart_async(
        points,
        title=f"{subscription.category.title} · {format_server_name(subscription)}",
    )
    try:
        attachment = await upload_message_photo(bot.api, message.peer_id, image)
    except Exception:
        logger.exception("Could not upload price chart to VK")
        await message.answer(
            f"{text}\n\nГрафик отправить не удалось, но цифры выше актуальны.",
            keyboard=main_menu_keyboard(),
        )
        return

    await message.answer(text, attachment=attachment, keyboard=main_menu_keyboard())
