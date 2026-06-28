"""add source + urgent to change_items

Adds the security-pipeline dimension. Both columns are NOT NULL with a server_default
so the migration is safe + non-breaking on the live DB (existing rows backfill to
source='drift', urgent=false).

Revision ID: c1a2b3d4e5f6
Revises: b00c8b315bae
Create Date: 2026-06-15 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1a2b3d4e5f6"
down_revision: str | Sequence[str] | None = "b00c8b315bae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "change_items", sa.Column("source", sa.String(), nullable=False, server_default="drift")
    )
    op.add_column(
        "change_items", sa.Column("urgent", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.create_index(op.f("ix_change_items_source"), "change_items", ["source"], unique=False)
    op.create_index(op.f("ix_change_items_urgent"), "change_items", ["urgent"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_change_items_urgent"), table_name="change_items")
    op.drop_index(op.f("ix_change_items_source"), table_name="change_items")
    op.drop_column("change_items", "urgent")
    op.drop_column("change_items", "source")
