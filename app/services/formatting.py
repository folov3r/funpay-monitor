"""Formatting helpers shared by bot messages and worker alerts."""

from __future__ import annotations

from decimal import Decimal

ITEM_TYPE_LABELS = {
    "предметы": "Предметы",
    "услуги": "Услуги",
    "гайды": "Гайды",
    "gamepass": "Gamepass",
    "c$": "C$",
    "аккаунты": "Аккаунты",
}


def format_money(value: Decimal | None) -> str:
    """Format a price in Russian style: 1 234,50 ₽ or 0,001191 ₽."""
    if value is None:
        return "—"
    if value != 0 and abs(value) < 1:
        formatted = f"{value:.6f}".rstrip("0").rstrip(".")
    else:
        formatted = f"{value:,.2f}"
    return f"{formatted.replace(',', ' ').replace('.', ',')} ₽"


def format_item_type(item_type: str | None) -> str | None:
    """Return a human-readable offer type label."""
    if not item_type:
        return None
    return ITEM_TYPE_LABELS.get(item_type, item_type[:1].upper() + item_type[1:])


def format_offer_filter(item_type: str | None, query: str | None) -> str | None:
    """Describe an optional type/title filter, or return ``None``."""
    parts: list[str] = []
    label = format_item_type(item_type)
    if label:
        parts.append(label)
    if query:
        parts.append(f"«{query}»")
    return " · ".join(parts) if parts else None


def format_percent(value: Decimal) -> str:
    """Format a percentage without trailing zeros: 7,5%."""
    formatted = f"{value:.1f}".replace(".", ",")
    return f"{formatted}%"
