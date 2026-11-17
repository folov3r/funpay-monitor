"""Tests for the local FastAPI application."""

from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal

import httpx
import pytest
from app.api.app import create_app
from app.parsers.base import BaseParser, CategoryInfo, Offer, ParsedCategory


class FakeParser(BaseParser):
    """Deterministic parser that never touches the network."""

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []

    async def fetch_category(self, url_path: str) -> ParsedCategory:
        self.calls.append(url_path)
        if url_path.startswith("/lots/"):
            return ParsedCategory(
                category=CategoryInfo(
                    funpay_id=2932,
                    type="lot",
                    title="Roblox",
                    url_path="/lots/2932/",
                    game_title="Roblox",
                    server_label="Способ передачи",
                ),
                offers=[
                    Offer(
                        seller_id=1,
                        seller_name="alpha",
                        amount=Decimal("1"),
                        price=Decimal("10.5"),
                        currency="RUB",
                        server_id=10,
                        server_name="Gift",
                        item_type="предметы",
                        title="Cosmic Relic",
                    ),
                    Offer(
                        seller_id=2,
                        seller_name="beta",
                        amount=Decimal("1"),
                        price=Decimal("7.25"),
                        currency="RUB",
                        server_id=10,
                        server_name="Gift",
                        item_type="предметы",
                        title="Cosmic Relic",
                    ),
                    Offer(
                        seller_id=3,
                        seller_name="gamma",
                        amount=None,
                        price=Decimal("99"),
                        currency="RUB",
                        server_id=10,
                        server_name="Gift",
                        item_type="услуги",
                        title="Boost",
                    ),
                ],
            )
        return ParsedCategory(
            category=CategoryInfo(
                funpay_id=30,
                type="chip",
                title="Albion Online Silver",
                url_path="/chips/30/",
                game_title="Albion Online",
                server_label="Сервер",
            ),
            offers=[
                Offer(
                    seller_id=1,
                    seller_name="alpha",
                    amount=Decimal("1000"),
                    price=Decimal("1.5"),
                    currency="RUB",
                    server_id=1,
                    server_name="Europe",
                ),
                Offer(
                    seller_id=2,
                    seller_name="beta",
                    amount=Decimal("500"),
                    price=Decimal("2.25"),
                    currency="RUB",
                    server_id=1,
                    server_name="Europe",
                ),
                Offer(
                    seller_id=3,
                    seller_name="gamma",
                    amount=Decimal("100"),
                    price=Decimal("0.75"),
                    currency="RUB",
                    server_id=2,
                    server_name="Asia",
                ),
            ],
        )

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def parser() -> FakeParser:
    return FakeParser()


@pytest.fixture
async def client(tmp_path: object, parser: FakeParser) -> AsyncIterator[httpx.AsyncClient]:
    path = tmp_path / "api.sqlite3"  # type: ignore[operator]
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{path}",
        enable_scheduler=False,
        parser=parser,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def test_health_reports_sqlite_and_disabled_scheduler(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"
    assert body["scheduler"] is False


async def test_import_creates_category_and_snapshot(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/categories/import",
        json={"url": "https://funpay.com/chips/30/"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["category"]["url_path"] == "/chips/30/"
    assert body["category"]["server_label"] == "Сервер"
    assert body["offers_found"] == 3
    assert body["snapshots_created"] == 2
    assert body["summary"]["offer_count"] == 3
    assert Decimal(body["summary"]["min_price"]) == Decimal("0.75")
    assert sorted(server["name"] for server in body["category"]["servers"]) == [
        "Asia",
        "Europe",
    ]

    listing = await client.get("/api/categories")
    assert listing.status_code == 200
    assert [row["title"] for row in listing.json()] == ["Albion Online Silver"]


async def test_import_rejects_foreign_url(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/categories/import",
        json={"url": "https://example.com/items/1/"},
    )

    assert response.status_code == 422


async def test_offers_and_history_are_filtered(client: httpx.AsyncClient) -> None:
    imported = await client.post(
        "/api/categories/import",
        json={"url": "https://funpay.com/lots/2932/"},
    )
    category_id = imported.json()["category"]["id"]

    offers = await client.get(
        f"/api/categories/{category_id}/offers",
        params={"item_type": "предметы", "query": "cosmic", "limit": 3},
    )
    assert offers.status_code == 200
    assert [Decimal(row["price"]) for row in offers.json()] == [
        Decimal("7.25"),
        Decimal("10.5"),
    ]

    summary = await client.get(
        f"/api/categories/{category_id}/summary",
        params={"item_type": "предметы"},
    )
    assert summary.json()["offer_count"] == 2

    history = await client.get(f"/api/categories/{category_id}/history")
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert Decimal(history.json()[0]["min_price"]) == Decimal("7.25")


async def test_subscription_lifecycle(client: httpx.AsyncClient) -> None:
    imported = await client.post(
        "/api/categories/import",
        json={"url": "https://funpay.com/chips/30/"},
    )
    category_id = imported.json()["category"]["id"]

    created = await client.post(
        "/api/subscriptions",
        json={
            "category_id": category_id,
            "mode": "abs",
            "threshold": "1.00",
        },
    )
    assert created.status_code == 201, created.text
    subscription = created.json()
    assert subscription["category_title"] == "Albion Online Silver"
    assert subscription["is_active"] is True

    listing = await client.get("/api/subscriptions")
    assert [row["id"] for row in listing.json()] == [subscription["id"]]

    stats = await client.get(f"/api/subscriptions/{subscription['id']}/stats")
    assert stats.status_code == 200
    stats_body = stats.json()
    assert stats_body["summary"]["offer_count"] == 3
    assert len(stats_body["history"]) == 1
    assert len(stats_body["cheapest"]) == 3

    deleted = await client.delete(f"/api/subscriptions/{subscription['id']}")
    assert deleted.status_code == 204
    assert (await client.get("/api/subscriptions")).json() == []


async def test_subscription_validation(client: httpx.AsyncClient) -> None:
    imported = await client.post(
        "/api/categories/import",
        json={"url": "https://funpay.com/chips/30/"},
    )
    category_id = imported.json()["category"]["id"]

    missing_threshold = await client.post(
        "/api/subscriptions",
        json={"category_id": category_id, "mode": "abs"},
    )
    assert missing_threshold.status_code == 422

    too_large_percent = await client.post(
        "/api/subscriptions",
        json={"category_id": category_id, "mode": "pct", "threshold": "150"},
    )
    assert too_large_percent.status_code == 422

    foreign_server = await client.post(
        "/api/subscriptions",
        json={
            "category_id": category_id,
            "server_id": 9999,
            "mode": "abs",
            "threshold": "1",
        },
    )
    assert foreign_server.status_code == 422


async def test_reparse_runs_alerts_and_reports(client: httpx.AsyncClient) -> None:
    imported = await client.post(
        "/api/categories/import",
        json={"url": "https://funpay.com/chips/30/"},
    )
    category_id = imported.json()["category"]["id"]
    await client.post(
        "/api/subscriptions",
        json={"category_id": category_id, "mode": "abs", "threshold": "5"},
    )

    response = await client.post(f"/api/categories/{category_id}/reparse")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["offers_found"] == 3
    assert body["snapshots_created"] == 2
    assert body["alerts_sent"] == 1

    notifications = await client.get("/api/notifications")
    assert notifications.status_code == 200
    assert len(notifications.json()) == 1
    assert notifications.json()[0]["category_title"] == "Albion Online Silver"

    status = await client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["categories"] == 1
    assert status.json()["active_subscriptions"] == 1


async def test_unknown_category_returns_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/categories/999")).status_code == 404
    assert (await client.post("/api/categories/999/reparse")).status_code == 404


async def test_import_returns_502_when_parser_fails(
    tmp_path: object,
) -> None:
    class BrokenParser(FakeParser):
        async def fetch_category(self, url_path: str) -> ParsedCategory:
            raise RuntimeError("markup changed")

    path = tmp_path / "broken.sqlite3"  # type: ignore[operator]
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{path}",
        enable_scheduler=False,
        parser=BrokenParser(),
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            response = await http.post(
                "/api/categories/import",
                json={"url": "https://funpay.com/chips/30/"},
            )

    assert response.status_code == 502
    assert "markup changed" in response.json()["detail"]
