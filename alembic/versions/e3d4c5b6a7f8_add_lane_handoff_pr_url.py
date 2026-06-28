"""add lane + handoff (json) + pr_url to change_items

Revision ID: e3d4c5b6a7f8
Revises: d2c3b4a5e6f7
Create Date: 2026-06-26
"""

import sqlalchemy as sa

from alembic import op

revision = "e3d4c5b6a7f8"
down_revision = "d2c3b4a5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "change_items",
        sa.Column("lane", sa.String(), nullable=False, server_default="infra-config"),
    )
    op.add_column("change_items", sa.Column("handoff", sa.JSON(), nullable=True))
    op.add_column("change_items", sa.Column("pr_url", sa.String(), nullable=True))
    op.create_index("ix_change_items_lane", "change_items", ["lane"])


def downgrade() -> None:
    op.drop_index("ix_change_items_lane", table_name="change_items")
    op.drop_column("change_items", "pr_url")
    op.drop_column("change_items", "handoff")
    op.drop_column("change_items", "lane")
