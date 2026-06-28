"""add handoff_brief + handed_off_at to change_items

Revision ID: d2c3b4a5e6f7
Revises: c1a2b3d4e5f6
Create Date: 2026-06-26
"""
import sqlalchemy as sa

from alembic import op

revision = "d2c3b4a5e6f7"
down_revision = "c1a2b3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_items", sa.Column("handoff_brief", sa.Text(), nullable=True))
    op.add_column("change_items", sa.Column("handed_off_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("change_items", "handed_off_at")
    op.drop_column("change_items", "handoff_brief")
