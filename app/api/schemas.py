"""Pydantic models for the local HTTP API."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ServerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    funpay_server_id: int
    name: str


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    funpay_id: int
    type: str
    title: str
    game_title: str | None = None
    url_path: str
    server_label: str | None = None
    is_active: bool
    last_parsed_at: datetime | None = None
    created_at: datetime
    servers: list[ServerOut] = Field(default_factory=list)


class PriceSummaryOut(BaseModel):
    min_price: Decimal
    median_price: Decimal
    offer_count: int


class OfferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    seller_id: int | None = None
    seller_name: str | None = None
    amount: Decimal | None = None
    price: Decimal
    currency: str
    item_type: str | None = None
    method: str | None = None
    title: str | None = None
    is_online: bool
    is_promo: bool
    parsed_at: datetime


class HistoryPointOut(BaseModel):
    captured_at: datetime
    min_price: Decimal
    median_price: Decimal
    offer_count: int


class ImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=500)


class ImportResultOut(BaseModel):
    category: CategoryOut
    item_types: list[str] = Field(default_factory=list)
    offers_found: int
    snapshots_created: int
    summary: PriceSummaryOut | None = None


class SubscriptionIn(BaseModel):
    category_id: int
    server_id: int | None = None
    mode: Literal["abs", "pct", "lowest"]
    threshold: Decimal | None = None
    item_type: str | None = Field(default=None, max_length=64)
    query: str | None = Field(default=None, max_length=255)


class SubscriptionUpdate(BaseModel):
    is_active: bool


class SubscriptionOut(BaseModel):
    id: int
    category_id: int
    category_title: str
    category_path: str
    server_id: int | None = None
    server_name: str | None = None
    item_type: str | None = None
    query: str | None = None
    mode: str
    threshold: Decimal | None = None
    is_active: bool
    created_at: datetime


class SubscriptionStatsOut(BaseModel):
    subscription: SubscriptionOut
    summary: PriceSummaryOut | None = None
    history: list[HistoryPointOut] = Field(default_factory=list)
    cheapest: list[OfferOut] = Field(default_factory=list)


class ParseRunOut(BaseModel):
    category_id: int
    category_title: str
    category_path: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    offers_found: int
    error_text: str | None = None


class StatusOut(BaseModel):
    categories: int
    active_categories: int
    users: int
    active_subscriptions: int
    offers: int
    parse_runs: list[ParseRunOut] = Field(default_factory=list)
    scheduler_state: str = "off"
    next_run_at: datetime | None = None
    last_run_at: datetime | None = None
    interval_minutes: int = 0


class NotificationOut(BaseModel):
    id: int
    subscription_id: int
    category_id: int
    category_title: str
    mode: str
    price: Decimal
    sent_at: datetime


class HealthOut(BaseModel):
    status: str
    version: str
    database: str
    scheduler: bool


class ReparseOut(BaseModel):
    category_id: int
    title: str
    status: str
    offers_found: int
    snapshots_created: int
    alerts_sent: int
    error_text: str | None = None
