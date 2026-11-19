"""Subscription soft delete

Revision ID: 9b3e5a1c7d20
Revises: 8f2c1d4e6a70
Create Date: 2026-11-19 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9b3e5a1c7d20"
down_revision: str | Sequence[str] | None = "8f2c1d4e6a70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Rows removed before this migration were only deactivated; treat them as
    # deleted so they do not come back in the desktop list.
    op.execute("UPDATE subscriptions SET deleted_at = created_at WHERE is_active = false")


def downgrade() -> None:
    op.drop_column("subscriptions", "deleted_at")
