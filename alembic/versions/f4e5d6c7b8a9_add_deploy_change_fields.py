"""add deploying-merge change fields to change_items (ADR-0019)

Adds the columns a proposed deploying merge needs, and relaxes the two
infrastructure-resource identifiers a proposal cannot have. `instance` and `rule_key`
stay NOT NULL: the proposal route fills both, so `GET /api/events` — which serializes
them into the factory-events feed — carries no new nulls.

The downgrade is asymmetric on purpose; its docstring says why.

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
    """Drop the columns; park the records; delete nothing; leave NOT NULL relaxed.

    This is the rollback path, and it has to work on a database where the feature was
    used — which is the only one where it matters. Three deliberate choices:

    * **Nothing is deleted.** `change_events.item_id` and `change_attempts.item_id`
      are real foreign keys with no cascade, and every deploy item has at least one
      event by construction, so `DELETE FROM change_items WHERE source = 'deploy'`
      cannot succeed on Postgres. Deleting the children first would succeed and
      destroy audit history to undo a schema change.
    * **NOT NULL is not restored**, because restoring it is what would require the
      delete. The direction is more permissive, and the previous build is unaffected:
      its only writer of these columns is `EscalationIn`, which requires both, so it
      never produces a null. A downgrade that gives back a working previous build is
      worth more than one that gives back a byte-identical schema.
    * **Deploy records are parked as `wontfix`.** The previous build has none of this
      branch's guards, so it would list an approved deploy change to the change-window
      executor and let it be claimed — the exact hazard this increment exists to
      prevent, re-opened by rolling back. `wontfix` is terminal, the executor pulls
      only `approved`, and `reconcile` spares it; `reactivate` is the way back.
    """
    op.execute(
        "INSERT INTO change_events (item_id, at, actor, event_type, "
        "from_status, to_status, detail) "
        "SELECT id, CURRENT_TIMESTAMP, 'migration', 'wontfixed', status, 'wontfix', "
        "'parked by the f4e5d6c7b8a9 downgrade: the previous build cannot refuse to "
        "execute a deploying-merge change' "
        "FROM change_items "
        "WHERE source = 'deploy' AND status NOT IN ('wontfix', 'resolved')"
    )
    op.execute(
        "UPDATE change_items SET status = 'wontfix' "
        "WHERE source = 'deploy' AND status NOT IN ('wontfix', 'resolved')"
    )
    op.drop_column("change_items", "rollback_plan")
    op.drop_column("change_items", "acceptance_criteria")
    op.drop_column("change_items", "change_class")
    op.drop_column("change_items", "pull_request_number")
    op.drop_column("change_items", "target_repository")
