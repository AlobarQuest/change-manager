"""add the work-proposal package locator to change_items (ADR-0026)

Three distinct columns rather than keys in `plan`, for the reason ADR-0019 gave when it
recorded `acceptance_criteria` and `rollback_plan` the same way: the proposal route REFUSES a
record that lacks them, and a refusal needs a column to be absent from. Null on every other
source.

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
Create Date: 2026-08-18
"""

import sqlalchemy as sa

from alembic import op

revision = "2c3d4e5f6a7b"
down_revision = "1b2c3d4e5f6a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_items", sa.Column("package_id", sa.String(), nullable=True))
    op.add_column("change_items", sa.Column("package_revision", sa.Integer(), nullable=True))
    op.add_column(
        "change_items", sa.Column("package_source_repository", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("change_items", "package_source_repository")
    op.drop_column("change_items", "package_revision")
    op.drop_column("change_items", "package_id")
