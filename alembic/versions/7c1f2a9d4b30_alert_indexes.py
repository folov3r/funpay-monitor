"""Indexes for alert evaluation

Revision ID: 7c1f2a9d4b30
Revises: f0377c9c9fc9
Create Date: 2026-11-13 09:10:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7c1f2a9d4b30"
down_revision: str | Sequence[str] | None = "f0377c9c9fc9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_subscriptions_category_active",
        "subscriptions",
        ["category_id", "is_active"],
        unique=False,
    )
    op.create_index(
        "ix_notifications_subscription_sent",
        "notifications",
        ["subscription_id", "sent_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_subscription_sent", table_name="notifications")
    op.drop_index("ix_subscriptions_category_active", table_name="subscriptions")
