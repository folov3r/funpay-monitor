"""Formatting helpers shared by bot messages and worker alerts."""

from __future__ import annotations

from decimal import Decimal


def format_money(value: Decimal | None) -> str:
    """Format a price in Russian style: 1 234,50 ₽."""
    if value is None:
        return "—"
    formatted = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} ₽"


def format_percent(value: Decimal) -> str:
    """Format a percentage without trailing zeros: 7,5%."""
    formatted = f"{value:.1f}".replace(".", ",")
    return f"{formatted}%"
