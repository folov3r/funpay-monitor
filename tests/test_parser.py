from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from app.parsers.base import ParserError
from app.parsers.funpay import (
    FunPayParser,
    detect_currency,
    normalize_category_path,
    parse_amount,
    parse_decimal,
)
from app.parsers.http import HttpClient

FIXTURES = Path(__file__).parent / "fixtures" / "funpay"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture
def parser() -> FunPayParser:
    return FunPayParser()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("/chips/30/", "/chips/30/"),
        ("/lots/13", "/lots/13/"),
        ("https://funpay.com/chips/30", "/chips/30/"),
        ("https://funpay.com/lots/13/?sort=price", "/lots/13/"),
        ("https://www.funpay.com/chips/30/", "/chips/30/"),
        ("funpay.com/chips/30/", "/chips/30/"),
        ("www.funpay.com/lots/13", "/lots/13/"),
    ],
)
def test_normalize_category_path(url: str, expected: str) -> None:
    assert normalize_category_path(url) == expected


@pytest.mark.parametrize("url", ["", "https://funpay.com/", "/chips/abc/", "/lots/13/offers/"])
def test_normalize_category_path_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_category_path(url)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("16.02", Decimal("16.02")),
        ("1 234,56", Decimal("1234.56")),
        ("10 009 ₽", Decimal("10009")),
        ("1.234.567", Decimal("1234567")),
        ("1,234,567", Decimal("1234567")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("нет цены", None),
    ],
)
def test_parse_decimal(raw: str, expected: Decimal | None) -> None:
    assert parse_decimal(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("50 кк", Decimal("50000000")),
        ("1 000 000 000 кк", Decimal("1000000000000000")),
        ("1 000 к", Decimal("1000000")),
        ("10 шт.", Decimal("10")),
        ("220", Decimal("220")),
        ("", None),
    ],
)
def test_parse_amount(raw: str, expected: Decimal | None) -> None:
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("16.02 ₽", "RUB"),
        ("$ 12.50", "USD"),
        ("12,50 €", "EUR"),
        ("5000 ₸", "KZT"),
        ("100", "RUB"),
    ],
)
def test_detect_currency(raw: str, expected: str) -> None:
    assert detect_currency(raw) == expected


def test_parse_chips_fixture(parser: FunPayParser) -> None:
    parsed = parser.parse_html(load_fixture("chips_30.html"), "/chips/30/")

    assert parsed.category.funpay_id == 30
    assert parsed.category.type == "chip"
    assert parsed.category.title == "Серебро Albion Online"
    assert parsed.category.url_path == "/chips/30/"
    assert len(parsed.offers) == 4

    promo = parsed.offers[0]
    assert promo.seller_id == 5979701
    assert promo.seller_name == "Hojmarket"
    assert promo.amount == Decimal("50000000")
    assert promo.price == Decimal("16.02")
    assert promo.currency == "RUB"
    assert promo.server_id == 8569
    assert promo.server_name == "Азия (Сингапур)"
    assert promo.is_online is True
    assert promo.is_promo is True

    regular = parsed.offers[1]
    assert regular.seller_id == 69228
    assert regular.amount == Decimal("220000000")
    assert regular.price == Decimal("14.54")
    assert regular.is_online is False
    assert regular.is_promo is False

    assert parsed.offers[3].amount == Decimal("1000000000000000")
    assert parsed.min_price == Decimal("14.54")
    assert parsed.median_price == Decimal("15.28")


def test_parse_lots_fixture(parser: FunPayParser) -> None:
    parsed = parser.parse_html(load_fixture("lots_13.html"), "/lots/13/")

    assert parsed.category.type == "lot"
    assert parsed.category.title == "Аккаунты World of Warcraft (RU, EU)"
    assert len(parsed.offers) == 3

    any_server = parsed.offers[0]
    assert any_server.server_id == 0
    assert any_server.server_name == "Любой"
    assert any_server.amount is None
    assert any_server.price == Decimal("117.11")
    assert any_server.seller_id == 445652
    assert any_server.is_promo is True

    kazzak = parsed.offers[1]
    assert kazzak.server_id == 1840
    assert kazzak.server_name == "Kazzak"
    assert kazzak.seller_id == 18683964
    assert kazzak.price == Decimal("2108")
    assert kazzak.is_online is True

    assert parsed.offers[2].is_online is False
    assert parsed.min_price == Decimal("117.11")
    assert parsed.median_price == Decimal("2108")


def test_parse_empty_category(parser: FunPayParser) -> None:
    parsed = parser.parse_html(load_fixture("empty_category.html"), "/chips/999/")

    assert parsed.offers == []
    assert parsed.min_price is None
    assert parsed.median_price is None


def test_parse_blocked_page_raises(parser: FunPayParser) -> None:
    with pytest.raises(ParserError):
        parser.parse_html(load_fixture("blocked.html"), "/chips/30/")


async def test_fetch_category_uses_http_client() -> None:
    html = load_fixture("chips_30.html")
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        assert request.headers["User-Agent"].startswith("Mozilla/5.0")
        return httpx.Response(200, text=html)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        http = HttpClient(client=client, delay=0)
        parser = FunPayParser(http_client=http)
        parsed = await parser.fetch_category("https://funpay.com/chips/30")

    assert seen_urls == ["https://funpay.com/chips/30/"]
    assert parsed.category.funpay_id == 30
    assert len(parsed.offers) == 4
