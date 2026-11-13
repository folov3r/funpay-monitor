"""Offer filters and higher price precision

Revision ID: 4d8e1b7c2a90
Revises: 7c1f2a9d4b30
Create Date: 2026-11-13 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4d8e1b7c2a90"
down_revision: str | Sequence[str] | None = "7c1f2a9d4b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("offers", sa.Column("item_type", sa.String(length=64), nullable=True))
    op.add_column("offers", sa.Column("method", sa.String(length=64), nullable=True))
    op.add_column("offers", sa.Column("title", sa.Text(), nullable=True))
    op.create_index(
        "ix_offers_category_type_price",
        "offers",
        ["category_id", "item_type", "price"],
        unique=False,
    )
    op.alter_column(
        "offers",
        "price",
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=sa.Numeric(precision=18, scale=6),
        existing_nullable=False,
    )

    op.add_column("price_snapshots", sa.Column("item_type", sa.String(length=64), nullable=True))
    op.add_column("price_snapshots", sa.Column("query", sa.String(length=255), nullable=True))
    op.drop_index("ix_price_snapshots_category_server_time", table_name="price_snapshots")
    op.create_index(
        "ix_price_snapshots_category_server_time",
        "price_snapshots",
        ["category_id", "server_id", "item_type", "query", "captured_at"],
        unique=False,
    )
    op.alter_column(
        "price_snapshots",
        "min_price",
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=sa.Numeric(precision=18, scale=6),
        existing_nullable=False,
    )
    op.alter_column(
        "price_snapshots",
        "median_price",
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=sa.Numeric(precision=18, scale=6),
        existing_nullable=False,
    )

    op.add_column("subscriptions", sa.Column("item_type", sa.String(length=64), nullable=True))
    op.add_column("subscriptions", sa.Column("query", sa.String(length=255), nullable=True))
    op.alter_column(
        "subscriptions",
        "threshold",
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=sa.Numeric(precision=18, scale=6),
        existing_nullable=True,
    )

    op.alter_column(
        "notifications",
        "price",
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=sa.Numeric(precision=18, scale=6),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "notifications",
        "price",
        existing_type=sa.Numeric(precision=18, scale=6),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=False,
    )

    op.alter_column(
        "subscriptions",
        "threshold",
        existing_type=sa.Numeric(precision=18, scale=6),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=True,
    )
    op.drop_column("subscriptions", "query")
    op.drop_column("subscriptions", "item_type")

    op.alter_column(
        "price_snapshots",
        "median_price",
        existing_type=sa.Numeric(precision=18, scale=6),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=False,
    )
    op.alter_column(
        "price_snapshots",
        "min_price",
        existing_type=sa.Numeric(precision=18, scale=6),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=False,
    )
    op.drop_index("ix_price_snapshots_category_server_time", table_name="price_snapshots")
    op.create_index(
        "ix_price_snapshots_category_server_time",
        "price_snapshots",
        ["category_id", "server_id", "captured_at"],
        unique=False,
    )
    op.drop_column("price_snapshots", "query")
    op.drop_column("price_snapshots", "item_type")

    op.alter_column(
        "offers",
        "price",
        existing_type=sa.Numeric(precision=18, scale=6),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=False,
    )
    op.drop_index("ix_offers_category_type_price", table_name="offers")
    op.drop_column("offers", "title")
    op.drop_column("offers", "method")
    op.drop_column("offers", "item_type")
