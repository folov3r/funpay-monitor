"""Text formatting and parsing helpers for bot handlers."""

from __future__ import annotations

import re
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from statistics import median

from app.db.models import Subscription
from app.db.repositories import PriceSummary
from app.parsers.funpay import normalize_category_path
from app.services.charts import ChartPoint
from app.services.formatting import format_item_type, format_money, format_offer_filter

FUNPAY_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?funpay\.com/(?:chips|lots)/\d+/?",
    re.IGNORECASE,
)
WHITESPACE_RE = re.compile(r"\s+")

MODE_LABELS = {
    "abs": "ниже порога",
    "pct": "падение в %",
    "lowest": "новый минимум",
}
MODE_BY_LABEL = {
    "ниже порога": "abs",
    "порог": "abs",
    "падение в %": "pct",
    "процент": "pct",
    "исторический минимум": "lowest",
    "минимум": "lowest",
}

ALL_ITEM_TYPES_LABEL = "Все"
SKIP_QUERY_LABEL = "Пропустить"
QUERY_PROMPT = (
    "Введите часть названия предмета для поиска, например plush nessie, "
    "или нажмите «Пропустить», чтобы следить за всеми предложениями выбранного типа."
)

WELCOME_TEXT = (
    "Привет! Я слежу за ценами на FunPay и присылаю уведомления, когда цена падает.\n\n"
    "Что умею:\n"
    "• добавлять подписки на лоты и игровую валюту;\n"
    "• следить за ценой ниже порога, падением на N% или новым минимумом;\n"
    "• строить график истории цен за 7 дней.\n\n"
    "Нажмите «Добавить» или пришлите ссылку на категорию FunPay."
)

HELP_TEXT = (
    "Команды:\n"
    "/start — главное меню\n"
    "/add — добавить подписку (можно сразу ссылкой)\n"
    "/list — мои подписки и текущие цены\n"
    "/stats <id> — график и статистика по подписке\n"
    "/unsubscribe <id> — удалить подписку\n"
    "/help — эта справка\n\n"
    "Ссылку можно присылать в виде https://funpay.com/chips/30/ "
    "или просто /chips/30/.\n\n"
    "Важно: VK разрешает сообществу писать только тем, кто написал ему первым."
)


def normalize_text(text: str | None) -> str:
    """Collapse whitespace and casefold for command/button matching."""
    return WHITESPACE_RE.sub(" ", text or "").strip().casefold()


def split_command(text: str | None) -> tuple[str, str]:
    """Return the first token (without @mention) and the rest of the message."""
    parts = (text or "").strip().split(maxsplit=1)
    if not parts:
        return "", ""
    command = parts[0].casefold().split("@", 1)[0]
    argument = parts[1] if len(parts) > 1 else ""
    return command, argument.strip()


def extract_category_path(text: str | None) -> str | None:
    """Extract a normalised FunPay category path from a message."""
    raw = (text or "").strip()
    if not raw:
        return None

    match = FUNPAY_URL_RE.search(raw)
    candidate = match.group(0) if match else raw.split(maxsplit=1)[0]
    try:
        return normalize_category_path(candidate)
    except ValueError:
        return None


def is_cancel(text: str | None) -> bool:
    return normalize_text(text) in {"отмена", "назад", "/cancel", "cancel"}


def is_add_command(text: str | None) -> bool:
    return split_command(text)[0] in {"/add", "добавить"}


def is_list_command(text: str | None) -> bool:
    return normalize_text(text) in {"/list", "мои подписки", "подписки"}


def is_stats_command(text: str | None) -> bool:
    return split_command(text)[0] in {"/stats", "статистика"}


def is_unsubscribe_command(text: str | None) -> bool:
    return split_command(text)[0] in {"/unsubscribe", "удалить", "отписаться"}


def parse_subscription_id(raw: str | None) -> int | None:
    """Parse ``3``, ``#3`` or ``Статистика #3`` into a subscription id."""
    match = re.search(r"#?(\d+)", raw or "")
    return int(match.group(1)) if match else None


def parse_threshold(text: str, mode: str) -> Decimal | None:
    """Parse a positive threshold; percentages are limited to 100."""
    cleaned = normalize_text(text).replace(" ", "").replace(",", ".")
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not value.is_finite() or value <= 0:
        return None
    if mode == "pct" and value > 100:
        return None
    return value


def mode_from_label(text: str | None) -> str | None:
    return MODE_BY_LABEL.get(normalize_text(text))


def item_type_from_label(text: str | None, available: Sequence[str]) -> tuple[bool, str | None]:
    """Resolve a type button/text into a stored value.

    Returns ``(matched, value)``. ``value=None`` means "all types" when the
    text matched the «Все» label; ``matched=False`` means the input is invalid.
    """
    normalized = normalize_text(text)
    if normalized in {normalize_text(ALL_ITEM_TYPES_LABEL), "все типы", "любой тип"}:
        return True, None
    for value in available:
        label = format_item_type(value) or value
        if normalized in {normalize_text(value), normalize_text(label)}:
            return True, value
    return False, None


def normalize_query(text: str | None) -> str | None:
    """Normalise a title search string, returning ``None`` for skip/empty."""
    normalized = normalize_text(text)
    if normalized in {"", normalize_text(SKIP_QUERY_LABEL), "пропустить", "нет"}:
        return None
    return normalized[:255]


def format_subscription_filter(subscription: Subscription) -> str | None:
    return format_offer_filter(
        getattr(subscription, "item_type", None),
        getattr(subscription, "query", None),
    )


def format_condition(mode: str, threshold: Decimal | None) -> str:
    """Describe an alert rule in human language."""
    if mode == "lowest":
        return "новый исторический минимум"
    if mode == "pct":
        percent = f"{threshold:g}" if threshold is not None else "?"
        return f"падение на {percent}%"
    return f"цена ниже {format_money(threshold)}"


def format_threshold(subscription: Subscription) -> str:
    return format_condition(subscription.mode, subscription.threshold)


def format_server_field(subscription: Subscription) -> str | None:
    """Render the server/delivery field with the label taken from FunPay.

    FunPay calls the same select "Сервер" on Albion and "Способ передачи" on
    Roblox, so the label is stored per category. ``None`` means the category
    has no such field at all (many /lots/ pages), and the line is omitted.
    """
    label = getattr(subscription.category, "server_label", None)
    if not label:
        return None
    if subscription.server is not None:
        return f"{label}: {subscription.server.name}"
    return f"{label}: любой"


def format_subscription_line(
    subscription: Subscription,
    summary: PriceSummary | None,
) -> str:
    current = (
        f"сейчас {format_money(summary.min_price)}" if summary is not None else "нет данных о цене"
    )
    details = []
    filter_label = format_subscription_filter(subscription)
    if filter_label:
        details.append(filter_label)
    server_field = format_server_field(subscription)
    if server_field:
        details.append(server_field)
    details.extend([format_threshold(subscription), current])
    return f"#{subscription.id} · {subscription.category.title}\n   " + " · ".join(details)


def format_subscription_list(
    subscriptions: Sequence[Subscription],
    summaries: dict[int, PriceSummary | None],
) -> str:
    if not subscriptions:
        return "У вас пока нет активных подписок. Пришлите ссылку FunPay или нажмите «Добавить»."
    lines = [format_subscription_line(sub, summaries.get(sub.id)) for sub in subscriptions]
    return "Ваши подписки:\n\n" + "\n\n".join(lines)


def format_stats_text(
    subscription: Subscription,
    current: PriceSummary | None,
    points: Sequence[ChartPoint],
    *,
    days: int = 7,
) -> str:
    lines = [f"#{subscription.id} · {subscription.category.title}"]
    filter_label = format_subscription_filter(subscription)
    if filter_label:
        lines.append(f"Фильтр: {filter_label}")
    server_field = format_server_field(subscription)
    if server_field:
        lines.append(server_field)
    lines.append(f"Условие: {format_threshold(subscription)}")
    if current is not None:
        lines.append(
            f"Сейчас: {format_money(current.min_price)} "
            f"(медиана {format_money(current.median_price)}, "
            f"офферов {current.offer_count})"
        )
    else:
        lines.append("Сейчас: нет актуальных офферов")

    if points:
        mins = [point.min_price for point in points]
        medians = [point.median_price for point in points]
        lines.append(
            f"За {days} дн.: минимум {format_money(min(mins))}, "
            f"медиана {format_money(median(medians))}, точек {len(points)}"
        )
    else:
        lines.append("История цен пока пуста: воркер ещё не собрал снапшоты.")

    return "\n".join(lines)
