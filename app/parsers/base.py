"""Common parser interfaces and data structures."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from statistics import median
from typing import Literal

CategoryType = Literal["chip", "lot"]


class ParserError(Exception):
    """Raised when a page cannot be parsed (e.g. markup changed or bot protection)."""


@dataclass(frozen=True, slots=True)
class Offer:
    """A single seller offer parsed from a marketplace page."""

    seller_id: int | None
    seller_name: str | None
    amount: Decimal | None
    price: Decimal
    currency: str
    server_id: int
    server_name: str
    is_online: bool = False
    is_promo: bool = False


@dataclass(frozen=True, slots=True)
class CategoryInfo:
    """Metadata of a tracked category."""

    funpay_id: int
    type: CategoryType
    title: str
    url_path: str
    game_title: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedCategory:
    """Result of parsing one category page."""

    category: CategoryInfo
    offers: list[Offer] = field(default_factory=list)

    @property
    def min_price(self) -> Decimal | None:
        """Cheapest offer price, if any."""
        return min((offer.price for offer in self.offers), default=None)

    @property
    def median_price(self) -> Decimal | None:
        """Median offer price, if any."""
        if not self.offers:
            return None
        return median(offer.price for offer in self.offers)


class BaseParser(ABC):
    """Interface every price source parser must implement."""

    @abstractmethod
    async def fetch_category(self, url_path: str) -> ParsedCategory:
        """Fetch a category page and return parsed metadata and offers."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release network resources."""
