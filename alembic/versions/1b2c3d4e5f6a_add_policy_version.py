"""add change_items.policy_version

ADR-0019 increment 5. Which version of the deploy policy approved a record.

WHY THE DOWNGRADE MAY DROP IT. The column is a projection of a decision whose durable record is
elsewhere: every policy approval also appends a `change_events` row whose `detail` names the
version, and that table is untouched here. So rolling the image back loses the queryable column
and not the finding — the same reasoning `0a1b2c3d4e5f` recorded for `deploy_observations`, and
the opposite of `f4e5d6c7b8a9`, whose rows WERE the audit trail.

There is no foreign key on this column in either direction, so the downgrade has no referential
work to do. That matters because this repository has been bitten precisely there: a downgrade that
is a guaranteed foreign-key violation on Postgres is GREEN in CI, because the migration tests run
on SQLite where foreign keys are not enforced. Exercised against real Postgres, both directions,
with rows present — not inferred from the absence of a relationship.

Nullable, with no backfill, and that is deliberate rather than lazy. A NOT NULL column would need
a value for every existing row, and there is no honest value: no existing record was approved by a
policy. In particular item 44 — approved before this mechanism existed, by a free-text actor over
the shared bearer, for a pull request that is now closed — keeps a null here. Backfilling it would
be fabricating a provenance, which is the failure this column exists to prevent.

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
"""

import sqlalchemy as sa

from alembic import op

revision = "1b2c3d4e5f6a"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("change_items", sa.Column("policy_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("change_items", "policy_version")
