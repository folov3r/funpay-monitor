"""Subscription commands and the /add finite-state dialog."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from vkbottle.bot import Bot, Message

from app.bot.cleanup import ChatCleaner
from app.bot.keyboards import (
    ANY_SERVER_LABEL,
    cancel_keyboard,
    confirm_keyboard,
    item_types_keyboard,
    main_menu_keyboard,
    modes_keyboard,
    query_keyboard,
    servers_keyboard,
    subscriptions_keyboard,
)
from app.bot.states import AddSubscriptionStates
from app.bot.texts import (
    QUERY_PROMPT,
    extract_category_path,
    format_condition,
    format_item_type,
    format_offer_filter,
    format_offer_summary,
    format_server_field,
    format_stats_text,
    format_subscription_list,
    is_add_command,
    is_cancel,
    is_list_command,
    is_stats_command,
    is_unsubscribe_command,
    item_type_from_label,
    mode_from_label,
    normalize_query,
    normalize_text,
    parse_subscription_id,
    parse_threshold,
    split_command,
)
from app.db.repositories import (
    cheapest_offers,
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
    admin_vk_ids: frozenset[int] = frozenset()
    alerts: Any = None
    cleaner: ChatCleaner = field(default_factory=ChatCleaner)

    def is_admin(self, vk_id: int) -> bool:
        return vk_id in self.admin_vk_ids


def _payload(message: Message) -> dict[str, Any]:
    peer = message.state_peer
    return dict(peer.payload) if peer is not None else {}


def _state_kwargs(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "state"}


def _track_dialog(services: BotServices, message: Message) -> None:
    """Remember the user's message so it can be deleted after a successful save."""
    services.cleaner.track(message.peer_id, [message.conversation_message_id])


async def _answer(
    message: Message,
    text: str,
    *,
    services: BotServices,
    **kwargs: Any,
) -> Any:
    """Send a dialog message and remember it for the chat cleanup."""
    sent = await message.answer(text, **kwargs)
    services.cleaner.track(message.peer_id, [sent.conversation_message_id])
    return sent


def _server_options(servers: list[Any]) -> list[dict[str, Any]]:
    return [
        {"id": server.id, "name": server.name} for server in servers if server.funpay_server_id != 0
    ]


def _server_label(payload: dict[str, Any]) -> str:
    """Human label of the page filter, e.g. "Сервер" or "Способ передачи"."""
    return str(payload.get("server_label") or "Сервер")


async def _reset_state(bot: Bot, message: Message) -> None:
    await bot.state_dispenser.delete(message.peer_id)


async def _send_price_summary(
    message: Message,
    services: BotServices,
    category_id: int,
    *,
    item_type: str | None,
    query: str | None,
) -> None:
    """Show the current min/median/count slice right where the filter is known."""
    async with services.session_factory() as session:
        summary = await current_price_summary(
            session,
            category_id,
            item_type=item_type,
            query=query,
        )
        offers = await cheapest_offers(
            session,
            category_id,
            item_type=item_type,
            query=query,
        )
    await _answer(
        message,
        format_offer_summary(summary, offers, item_type=item_type, query=query),
        services=services,
    )


async def _import_category(
    bot: Bot,
    message: Message,
    services: BotServices,
    url_path: str,
) -> None:
    await _answer(
        message,
        "Проверяю категорию на FunPay, это может занять несколько секунд…",
        services=services,
    )
    try:
        imported = await services.monitoring.import_category(url_path)
    except Exception:
        logger.exception("Could not import category %s", url_path)
        await _answer(
            message,
            "Не удалось загрузить страницу FunPay. Проверьте, что ссылка ведёт "
            "на категорию /chips/… или /lots/…, и попробуйте ещё раз.",
            services=services,
            keyboard=main_menu_keyboard(),
        )
        return

    async with services.session_factory() as session:
        servers = await list_servers(session, imported.category_id)

    payload = {
        "category_id": imported.category_id,
        "category_title": imported.title,
        "url_path": imported.url_path,
        "offers_found": imported.offers_found,
        "servers": _server_options(servers),
        "item_types": list(imported.item_types),
        "server_label": imported.server_label,
    }
    await _answer(
        message,
        f"Категория «{imported.title}»: {imported.offers_found} офферов.",
        services=services,
    )

    if imported.item_types:
        await _ask_item_type(bot, message, payload, services)
    else:
        # /chips/ categories have no item types or name step, so the filter is
        # known right away — show the whole-category slice before the server.
        await _send_price_summary(
            message,
            services,
            imported.category_id,
            item_type=None,
            query=None,
        )
        await _ask_server(bot, message, payload, services)


async def _ask_item_type(
    bot: Bot,
    message: Message,
    payload: dict[str, Any],
    services: BotServices,
) -> None:
    await bot.state_dispenser.set(
        message.peer_id,
        AddSubscriptionStates.WAITING_ITEM_TYPE,
        **_state_kwargs(payload),
    )
    labels = [
        format_item_type(item_type) or item_type for item_type in payload.get("item_types") or []
    ]
    await _answer(
        message,
        "Что отслеживать? Выберите тип предложений:",
        services=services,
        keyboard=item_types_keyboard(labels),
    )


async def _ask_query(
    bot: Bot,
    message: Message,
    payload: dict[str, Any],
    services: BotServices,
) -> None:
    await bot.state_dispenser.set(
        message.peer_id,
        AddSubscriptionStates.WAITING_QUERY,
        **_state_kwargs(payload),
    )
    await _answer(message, QUERY_PROMPT, services=services, keyboard=query_keyboard())


async def _ask_server(
    bot: Bot,
    message: Message,
    payload: dict[str, Any],
    services: BotServices,
) -> None:
    options = payload.get("servers") or []
    if not options:
        await _answer(
            message,
            "У этой категории нет выбора сервера — подписка будет на все предложения.",
            services=services,
        )
        await _ask_mode(bot, message, payload, services, server_id=None, server_name=None)
        return

    await bot.state_dispenser.set(
        message.peer_id,
        AddSubscriptionStates.WAITING_SERVER,
        **_state_kwargs(payload),
    )
    label = _server_label(payload)
    names = [option["name"] for option in options]
    await _answer(
        message,
        f"Выберите {label.lower()} (можно прислать название текстом):",
        services=services,
        keyboard=servers_keyboard(names),
    )


async def _ask_mode(
    bot: Bot,
    message: Message,
    payload: dict[str, Any],
    services: BotServices,
    *,
    server_id: int | None,
    server_name: str | None,
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
    await _answer(
        message,
        "Когда присылать уведомление?",
        services=services,
        keyboard=modes_keyboard(),
    )


async def _ask_confirm(
    bot: Bot,
    message: Message,
    payload: dict[str, Any],
    services: BotServices,
) -> None:
    mode = str(payload.get("mode", "abs"))
    threshold_raw = payload.get("threshold")
    threshold = Decimal(str(threshold_raw)) if threshold_raw is not None else None
    condition = format_condition(mode, threshold)
    server_name = payload.get("server_name")
    server_label = payload.get("server_label")
    title = str(payload.get("category_title") or "категория")
    filter_label = format_offer_filter(
        payload.get("item_type"),
        payload.get("query"),
    )

    lines = [f"Проверьте подписку:\n\n{title}"]
    if filter_label:
        lines.append(f"Фильтр: {filter_label}")
    if server_label and server_name:
        lines.append(f"{server_label}: {server_name}")
    lines.append(f"Условие: {condition}")

    await bot.state_dispenser.set(
        message.peer_id,
        AddSubscriptionStates.WAITING_CONFIRM,
        **_state_kwargs(payload),
    )
    await _answer(
        message,
        "\n".join(lines),
        services=services,
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
                item_type=subscription.item_type,
                query=subscription.query,
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
        services.cleaner.reset(message.peer_id)
        _track_dialog(services, message)
        _, argument = split_command(message.text)
        path = extract_category_path(argument)
        if path is None:
            await bot.state_dispenser.set(
                message.peer_id,
                AddSubscriptionStates.WAITING_LINK,
            )
            await _answer(
                message,
                "Пришлите ссылку на категорию FunPay, например https://funpay.com/chips/30/",
                services=services,
                keyboard=cancel_keyboard(),
            )
            return
        await _import_category(bot, message, services, path)

    @bot.on.message(func=lambda message: extract_category_path(message.text) is not None)
    async def link_handler(message: Message, user_id: int) -> None:
        _track_dialog(services, message)
        path = extract_category_path(message.text)
        if path is None:  # pragma: no cover - guarded by the rule above
            return
        await _import_category(bot, message, services, path)

    @bot.on.message(func=lambda message: is_cancel(message.text))
    async def cancel_handler(message: Message, user_id: int) -> None:
        await _reset_state(bot, message)
        services.cleaner.forget(message.peer_id)
        await message.answer("Отменено.", keyboard=main_menu_keyboard())

    @bot.on.message(func=lambda message: is_list_command(message.text))
    async def list_handler(message: Message, user_id: int) -> None:
        await _reset_state(bot, message)
        services.cleaner.forget(message.peer_id)
        await _send_subscription_list(message, services, user_id)

    @bot.on.message(func=lambda message: is_stats_command(message.text))
    async def stats_handler(message: Message, user_id: int) -> None:
        await _reset_state(bot, message)
        services.cleaner.forget(message.peer_id)
        _, argument = split_command(message.text)
        subscription_id = parse_subscription_id(argument)
        if subscription_id is None:
            await _send_subscription_list(message, services, user_id)
            return
        await _send_stats(bot, message, services, user_id, subscription_id)

    @bot.on.message(func=lambda message: is_unsubscribe_command(message.text))
    async def unsubscribe_handler(message: Message, user_id: int) -> None:
        await _reset_state(bot, message)
        services.cleaner.forget(message.peer_id)
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
        _track_dialog(services, message)
        path = extract_category_path(message.text)
        if path is None:
            await _answer(
                message,
                "Не вижу ссылку FunPay. Пришлите, например, https://funpay.com/chips/30/",
                services=services,
                keyboard=cancel_keyboard(),
            )
            return
        await _import_category(bot, message, services, path)

    @bot.on.message(state=AddSubscriptionStates.WAITING_ITEM_TYPE)
    async def waiting_item_type_handler(message: Message, user_id: int) -> None:
        _track_dialog(services, message)
        payload = _payload(message)
        available = payload.get("item_types") or []
        matched, item_type = item_type_from_label(message.text, available)
        if not matched:
            labels = [format_item_type(value) or value for value in available]
            await _answer(
                message,
                "Выберите тип кнопкой.",
                services=services,
                keyboard=item_types_keyboard(labels),
            )
            return
        await _ask_query(bot, message, {**payload, "item_type": item_type}, services)

    @bot.on.message(state=AddSubscriptionStates.WAITING_QUERY)
    async def waiting_query_handler(message: Message, user_id: int) -> None:
        _track_dialog(services, message)
        payload = {**_payload(message), "query": normalize_query(message.text)}
        category_id = payload.get("category_id")
        if category_id is not None:
            await _send_price_summary(
                message,
                services,
                int(category_id),
                item_type=payload.get("item_type"),
                query=payload.get("query"),
            )
        await _ask_server(bot, message, payload, services)

    @bot.on.message(state=AddSubscriptionStates.WAITING_SERVER)
    async def waiting_server_handler(message: Message, user_id: int) -> None:
        _track_dialog(services, message)
        payload = _payload(message)
        text = normalize_text(message.text)
        options = payload.get("servers") or []

        if text == normalize_text(ANY_SERVER_LABEL):
            await _ask_mode(
                bot,
                message,
                payload,
                services,
                server_id=None,
                server_name="любой",
            )
            return

        chosen = next(
            (option for option in options if normalize_text(option["name"]) == text),
            None,
        )
        if chosen is None:
            label = _server_label(payload)
            await _answer(
                message,
                f"Выберите {label.lower()} кнопкой или пришлите его название.",
                services=services,
                keyboard=servers_keyboard([option["name"] for option in options]),
            )
            return

        await _ask_mode(
            bot,
            message,
            payload,
            services,
            server_id=int(chosen["id"]),
            server_name=str(chosen["name"]),
        )

    @bot.on.message(state=AddSubscriptionStates.WAITING_MODE)
    async def waiting_mode_handler(message: Message, user_id: int) -> None:
        _track_dialog(services, message)
        mode = mode_from_label(message.text)
        if mode is None:
            await _answer(
                message,
                "Выберите условие кнопкой.",
                services=services,
                keyboard=modes_keyboard(),
            )
            return

        payload = _payload(message)
        if mode == "lowest":
            await _ask_confirm(bot, message, {**payload, "mode": mode, "threshold": None}, services)
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
        await _answer(message, prompt, services=services, keyboard=cancel_keyboard())

    @bot.on.message(state=AddSubscriptionStates.WAITING_THRESHOLD)
    async def waiting_threshold_handler(message: Message, user_id: int) -> None:
        _track_dialog(services, message)
        payload = _payload(message)
        mode = str(payload.get("mode", "abs"))
        threshold = parse_threshold(message.text or "", mode)
        if threshold is None:
            hint = (
                "Нужно положительное число до 100."
                if mode == "pct"
                else "Нужно положительное число, например 1450 или 1450,50."
            )
            await _answer(message, hint, services=services, keyboard=cancel_keyboard())
            return

        await _ask_confirm(
            bot,
            message,
            {**payload, "threshold": str(threshold)},
            services,
        )

    @bot.on.message(state=AddSubscriptionStates.WAITING_CONFIRM)
    async def waiting_confirm_handler(message: Message, user_id: int) -> None:
        _track_dialog(services, message)
        if normalize_text(message.text) not in {"сохранить", "да", "подтвердить"}:
            await _answer(
                message,
                "Нажмите «Сохранить» или «Отмена».",
                services=services,
                keyboard=confirm_keyboard(),
            )
            return

        payload = _payload(message)
        category_id = payload.get("category_id")
        mode = payload.get("mode")
        if category_id is None or mode not in {"abs", "pct", "lowest"}:
            await _reset_state(bot, message)
            services.cleaner.forget(message.peer_id)
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
                item_type=payload.get("item_type"),
                query=payload.get("query"),
            )
            await session.commit()
            subscription_id = subscription.id

        await _reset_state(bot, message)
        sent = await _answer(
            message,
            f"Подписка #{subscription_id} сохранена. "
            "Как только воркер соберёт свежие цены, бот проверит условие.",
            services=services,
            keyboard=main_menu_keyboard(),
        )
        deleted = await services.cleaner.purge(
            bot.api,
            message.peer_id,
            keep=[sent.conversation_message_id],
        )
        logger.info(
            "Saved subscription %s for peer %s, cleaned up %s dialog messages",
            subscription_id,
            message.peer_id,
            deleted,
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
            item_type=subscription.item_type,
            query=subscription.query,
        )
        if subscription.server_id is None:
            aggregates = await list_aggregated_snapshots(
                session,
                subscription.category_id,
                item_type=subscription.item_type,
                query=subscription.query,
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
                item_type=subscription.item_type,
                query=subscription.query,
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

    filter_label = format_offer_filter(subscription.item_type, subscription.query)
    title_parts = [subscription.category.title]
    if filter_label:
        title_parts.append(filter_label)
    server_field = format_server_field(subscription)
    if server_field:
        title_parts.append(server_field)
    image = await render_price_chart_async(
        points,
        title=" · ".join(title_parts),
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
