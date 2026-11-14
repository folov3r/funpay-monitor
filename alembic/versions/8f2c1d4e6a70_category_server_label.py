"""Store the page filter label on categories

Revision ID: 8f2c1d4e6a70
Revises: 4d8e1b7c2a90
Create Date: 2026-11-14 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8f2c1d4e6a70"
down_revision: str | Sequence[str] | None = "4d8e1b7c2a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("categories", sa.Column("server_label", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("categories", "server_label")
