"""SQLAlchemy models for the FunPay Monitor database."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vk_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255))
    is_admin: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Category(Base):
    """A FunPay category being tracked, e.g. Albion Online Silver (/chips/30/)."""

    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("funpay_id", "type", name="uq_categories_funpay_id_type"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    funpay_id: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # 'chip' | 'lot'
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    game_title: Mapped[str | None] = mapped_column(String(255))
    url_path: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)
    last_parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    servers: Mapped[list[Server]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class Server(Base):
    """A game server/realm that offers belong to."""

    __tablename__ = "servers"
    __table_args__ = (
        UniqueConstraint("category_id", "funpay_server_id", name="uq_servers_category_server"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    funpay_server_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)

    category: Mapped[Category] = relationship(back_populates="servers")


class Offer(Base):
    """Current offers for a category (rewritten on every parse run)."""

    __tablename__ = "offers"
    __table_args__ = (
        Index("ix_offers_category_server_price", "category_id", "server_id", "price"),
        Index("ix_offers_category_type_price", "category_id", "item_type", "price"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    seller_id: Mapped[int | None] = mapped_column(BigInteger)
    seller_name: Mapped[str | None] = mapped_column(String(255))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), server_default="RUB", nullable=False)
    item_type: Mapped[str | None] = mapped_column(String(64))
    method: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str | None] = mapped_column(Text)
    is_online: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    is_promo: Mapped[bool] = mapped_column(Boolean, server_default=false(), nullable=False)
    parsed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PriceSnapshot(Base):
    """Aggregated price history used for charts and alert conditions."""

    __tablename__ = "price_snapshots"
    __table_args__ = (
        Index(
            "ix_price_snapshots_category_server_time",
            "category_id",
            "server_id",
            "item_type",
            "query",
            "captured_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    server_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="CASCADE"), nullable=False
    )
    min_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    median_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    offer_count: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str | None] = mapped_column(String(255))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ParseRun(Base):
    """Journal of parser runs, used by /status and diagnostics."""

    __tablename__ = "parse_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # 'ok' | 'error' | 'partial'
    offers_found: Mapped[int] = mapped_column(Integer, server_default="0", nullable=False)
    error_text: Mapped[str | None] = mapped_column(Text)


class Subscription(Base):
    """A user's alert rule for a category (optionally narrowed to one server)."""

    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_subscriptions_category_active", "category_id", "is_active"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    server_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("servers.id", ondelete="SET NULL")
    )
    item_type: Mapped[str | None] = mapped_column(String(64))
    query: Mapped[str | None] = mapped_column(String(255))
    mode: Mapped[str] = mapped_column(String(16), nullable=False)  # 'abs' | 'pct' | 'lowest'
    threshold: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=true(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="subscriptions")
    category: Mapped[Category] = relationship()
    server: Mapped[Server | None] = relationship()
    notifications: Mapped[list[Notification]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan"
    )


class Notification(Base):
    """Log of sent alerts, also used for per-subscription cooldown."""

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_subscription_sent", "subscription_id", "sent_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("price_snapshots.id", ondelete="CASCADE"), nullable=False
    )
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)  # 'abs' | 'pct' | 'lowest'

    subscription: Mapped[Subscription] = relationship(back_populates="notifications")
