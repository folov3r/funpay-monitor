"""FunPay parser for ``/chips/{id}/`` and ``/lots/{id}/`` category pages."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from app.config import get_settings
from app.parsers.base import (
    BaseParser,
    CategoryInfo,
    CategoryType,
    Offer,
    ParsedCategory,
    ParserError,
)
from app.parsers.http import HttpClient

logger = logging.getLogger(__name__)

BASE_URL = "https://funpay.com"

CATEGORY_PATH_RE = re.compile(r"^/(chips|lots)/(\d+)/?$")
CATEGORY_TYPE_BY_SEGMENT: dict[str, CategoryType] = {"chips": "chip", "lots": "lot"}

SELLER_ID_RE = re.compile(r"/users/(\d+)")
WHITESPACE_RE = re.compile(r"[\s\u00a0\u202f]+")
NON_NUMBER_RE = re.compile(r"[^\d.,]")

CURRENCY_MARKERS: tuple[tuple[str, str], ...] = (
    ("₽", "RUB"),
    ("руб", "RUB"),
    ("rub", "RUB"),
    ("$", "USD"),
    ("usd", "USD"),
    ("долл", "USD"),
    ("€", "EUR"),
    ("eur", "EUR"),
    ("евро", "EUR"),
    ("₸", "KZT"),
    ("kzt", "KZT"),
    ("тенге", "KZT"),
    ("₴", "UAH"),
    ("uah", "UAH"),
    ("грн", "UAH"),
    ("£", "GBP"),
    ("gbp", "GBP"),
    ("byn", "BYN"),
)

AMOUNT_MULTIPLIERS: tuple[tuple[str, Decimal], ...] = (
    ("млрд", Decimal("1000000000")),
    ("млн", Decimal("1000000")),
    ("кк", Decimal("1000000")),
    ("kk", Decimal("1000000")),
    ("м", Decimal("1000000")),
    ("к", Decimal("1000")),
    ("k", Decimal("1000")),
    ("b", Decimal("1000000000")),
    ("m", Decimal("1000000")),
)


def normalize_category_path(url: str) -> str:
    """Turn any FunPay category URL (or path) into ``/chips/{id}/`` or ``/lots/{id}/``."""
    raw = url.strip()
    if not raw:
        raise ValueError("category URL is empty")

    path = urlparse(raw).path if "://" in raw else raw
    path = re.sub(r"^(?:www\.)?funpay\.com", "", path, flags=re.IGNORECASE)
    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path

    match = CATEGORY_PATH_RE.match(path)
    if match is None:
        raise ValueError(f"unsupported FunPay category URL: {url!r}")

    segment, funpay_id = match.groups()
    return f"/{segment}/{funpay_id}/"


def parse_decimal(raw: str) -> Decimal | None:
    """Parse a human-formatted number, e.g. ``1 234,56`` or ``10 009``."""
    cleaned = NON_NUMBER_RE.sub("", WHITESPACE_RE.sub("", raw))
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        groups = cleaned.split(",")
        if len(groups) > 1 and all(len(group) == 3 for group in groups[1:]):
            cleaned = "".join(groups)
        else:
            cleaned = cleaned.replace(",", ".")
    elif cleaned.count(".") > 1:
        groups = cleaned.split(".")
        if all(len(group) == 3 for group in groups[1:]):
            cleaned = "".join(groups)
        else:
            integer_part, _, fractional_part = cleaned.rpartition(".")
            cleaned = integer_part.replace(".", "") + "." + fractional_part

    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def detect_currency(raw: str) -> str:
    """Map a price suffix to an ISO currency code (RUB when unknown)."""
    lowered = raw.casefold()
    for marker, code in CURRENCY_MARKERS:
        if marker in lowered:
            return code
    return "RUB"


def parse_amount(raw: str) -> Decimal | None:
    """Parse the quantity of a chip offer, normalising ``кк`` to millions."""
    lowered = WHITESPACE_RE.sub("", raw).casefold()
    value = parse_decimal(lowered)
    if value is None:
        return None

    for suffix, multiplier in AMOUNT_MULTIPLIERS:
        if suffix in lowered:
            return value * multiplier
    return value


def _text(node: Tag | None) -> str:
    if node is None:
        return ""
    return WHITESPACE_RE.sub(" ", node.get_text(" ", strip=True)).strip()


def _attr_text(node: Tag, name: str) -> str | None:
    """Read a whitespace-normalised string attribute from a tag."""
    raw = node.get(name)
    if isinstance(raw, list):
        raw = " ".join(str(part) for part in raw)
    if not isinstance(raw, str):
        return None
    value = WHITESPACE_RE.sub(" ", raw).strip()
    return value or None


def _parse_price(price_node: Tag) -> tuple[Decimal | None, str]:
    """Return the exact price and the displayed price text.

    FunPay stores the unrounded value in ``data-s`` and rounds the visible
    price to two decimals (or five for cheap offers). ``data-s`` is used only
    when it agrees with the visible price, so synthetic or legacy markup with
    unrelated ``data-s`` values still falls back to the text.
    """
    price_value_node = price_node.find("div", recursive=False) or price_node
    price_text = _text(price_value_node)
    displayed = parse_decimal(price_text)

    raw_exact = price_node.get("data-s")
    exact = parse_decimal(raw_exact) if isinstance(raw_exact, str) else None
    if exact is not None and exact > 0:
        if displayed is None or displayed <= 0:
            return exact, price_text
        tolerance = max(Decimal("0.01"), displayed * Decimal("0.001"))
        if abs(exact - displayed) <= tolerance:
            return exact, price_text
    return displayed, price_text


def _parse_server(item: Tag) -> tuple[int, str]:
    raw_id = item.get("data-server")
    server_id = 0
    if isinstance(raw_id, str) and raw_id != "*":
        try:
            server_id = int(raw_id)
        except ValueError:
            server_id = 0

    server_name = _text(item.select_one(".tc-server"))
    if not server_name:
        server_name = "Любой" if raw_id == "*" else "Неизвестно"
    return server_id, server_name


def _parse_seller_id(item: Tag) -> int | None:
    raw_id = item.get("data-user")
    if isinstance(raw_id, str) and raw_id.isdigit():
        return int(raw_id)

    avatar = item.select_one(".avatar-photo[data-href]")
    href = avatar.get("data-href") if avatar is not None else None
    if href is None:
        link = item.select_one('a[href*="/users/"]')
        href = link.get("href") if link is not None else None

    if href is None:
        return None
    match = SELLER_ID_RE.search(str(href))
    return int(match.group(1)) if match else None


def _parse_offer(item: Tag) -> Offer | None:
    price_node = item.select_one(".tc-price")
    if price_node is None:
        logger.warning("Offer without price node skipped: %s", item.get("href"))
        return None

    # The first nested div holds the actual price; extra divs may hold promo icons.
    price, price_text = _parse_price(price_node)
    if price is None or price <= 0:
        logger.warning("Offer with unparsable price %r skipped: %s", price_text, item.get("href"))
        return None

    amount_node = item.select_one(".tc-amount")
    amount = parse_amount(_text(amount_node)) if amount_node is not None else None

    server_id, server_name = _parse_server(item)
    classes = item.get("class") or []
    is_online = item.get("data-online") == "1" or item.select_one(".media-user.online") is not None
    item_type = _attr_text(item, "data-f-type")
    method = _attr_text(item, "data-f-method")
    title = _text(item.select_one(".tc-desc-text")) or None

    return Offer(
        seller_id=_parse_seller_id(item),
        seller_name=_text(item.select_one(".media-user-name")) or None,
        amount=amount,
        price=price,
        currency=detect_currency(price_text),
        server_id=server_id,
        server_name=server_name,
        is_online=is_online,
        is_promo="offer-promo" in classes,
        item_type=item_type.casefold() if item_type else None,
        method=method.casefold() if method else None,
        title=title,
    )


class FunPayParser(BaseParser):
    """Parse FunPay category pages using the server-rendered HTML table."""

    def __init__(self, *, http_client: HttpClient | None = None) -> None:
        settings = get_settings()
        self._http = http_client or HttpClient(delay=settings.request_delay_seconds)

    async def fetch_category(self, url_path: str) -> ParsedCategory:
        path = normalize_category_path(url_path)
        response = await self._http.get(f"{BASE_URL}{path}")
        # BeautifulSoup + lxml are CPU-bound and a busy category page (3000+
        # offers) takes seconds to parse. Run it in a worker thread so a bot
        # request does not stall Long Poll and other handlers on the event loop.
        started = time.perf_counter()
        parsed = await asyncio.to_thread(self.parse_html, response.text, path)
        logger.debug(
            "Parsed %s offers from %s in %.2fs",
            len(parsed.offers),
            path,
            time.perf_counter() - started,
        )
        return parsed

    async def aclose(self) -> None:
        await self._http.aclose()

    def parse_html(self, html: str, url_path: str) -> ParsedCategory:
        """Parse an already downloaded category page (used by tests and fixtures)."""
        path = normalize_category_path(url_path)
        match = CATEGORY_PATH_RE.match(path)
        assert match is not None  # guaranteed by normalize_category_path
        segment, raw_funpay_id = match.groups()

        soup = BeautifulSoup(html, "lxml")
        title = _text(soup.select_one("h1"))
        if not title:
            raise ParserError(
                f"category title not found at {path}: markup changed or bot protection page"
            )

        offers: list[Offer] = []
        for item in soup.select("a.tc-item"):
            offer = _parse_offer(item)
            if offer is not None:
                offers.append(offer)

        category = CategoryInfo(
            funpay_id=int(raw_funpay_id),
            type=CATEGORY_TYPE_BY_SEGMENT[segment],
            title=title,
            url_path=path,
        )
        logger.debug("Parsed %s offers from %s", len(offers), path)
        return ParsedCategory(category=category, offers=offers)
