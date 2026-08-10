"""add deploying-merge change fields to change_items (ADR-0019)

Adds the columns a proposed deploying merge needs, and relaxes the two
infrastructure-resource identifiers a proposal cannot have. `instance` and `rule_key`
stay NOT NULL: the proposal route fills both, so `GET /api/events` — which serializes
them into the factory-events feed — carries no new nulls.

Revision ID: f4e5d6c7b8a9
Revises: e3d4c5b6a7f8
Create Date: 2026-08-10
"""

import sqlalchemy as sa

from alembic import op

revision = "f4e5d6c7b8a9"
down_revision = "e3d4c5b6a7f8"
branch_labels = None
depends_on = None

# SQLite cannot ALTER COLUMN, and tests/test_migration.py runs this against SQLite.
_RELAXED = ("resource_uuid", "resource_name")


def upgrade() -> None:
    op.add_column("change_items", sa.Column("target_repository", sa.String(), nullable=True))
    op.add_column("change_items", sa.Column("pull_request_number", sa.Integer(), nullable=True))
    op.add_column("change_items", sa.Column("change_class", sa.String(), nullable=True))
    op.add_column("change_items", sa.Column("acceptance_criteria", sa.JSON(), nullable=True))
    op.add_column("change_items", sa.Column("rollback_plan", sa.JSON(), nullable=True))
    with op.batch_alter_table("change_items") as batch:
        for column in _RELAXED:
            batch.alter_column(column, existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Deploy items have no resource_uuid/resource_name, so restoring NOT NULL would
    # fail on any row this migration made possible. Delete them first — they are the
    # only rows that can be null, and only this migration could have created them.
    op.execute("DELETE FROM change_items WHERE source = 'deploy'")
    with op.batch_alter_table("change_items") as batch:
        for column in _RELAXED:
            batch.alter_column(column, existing_type=sa.String(), nullable=False)
    op.drop_column("change_items", "rollback_plan")
    op.drop_column("change_items", "acceptance_criteria")
    op.drop_column("change_items", "change_class")
    op.drop_column("change_items", "pull_request_number")
    op.drop_column("change_items", "target_repository")
