"""add deploy_observations

ADR-0019 increment 2. One append-only table recording what a watcher observed of the rollout a
deploying merge caused.

WHY THE DOWNGRADE MAY DROP IT, when the previous migration's downgrade deliberately deleted
nothing. `f4e5d6c7b8a9` could not delete because its rows WERE the audit trail; here they are
not. Every observation appends a `change_events` row whose `detail` is written to be
self-contained — the merge commit in full, the run id, attempt, conclusion and URL, the workflow
revision and what a green run at those bytes attests. That table is untouched by this downgrade,
so rolling the image back loses the queryable projection and not the finding.

There is also no foreign-key violation to walk into, which is the trap the previous downgrade hit
and which was invisible in CI because the migration tests run on SQLite where foreign keys are
off. `deploy_observations` is the child in the only relationship it participates in, so dropping
it removes the referencing side. Verified on real Postgres with rows present, both directions,
rather than inferred from that asymmetry.

Revision ID: 0a1b2c3d4e5f
Revises: f4e5d6c7b8a9
"""

import sqlalchemy as sa

from alembic import op

revision = "0a1b2c3d4e5f"
down_revision = "f4e5d6c7b8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deploy_observations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "item_id",
            sa.Integer(),
            sa.ForeignKey("change_items.id"),
            nullable=False,
        ),
        sa.Column("observation_key", sa.String(), nullable=False),
        sa.Column("merge_commit_sha", sa.String(), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("production_reached", sa.String(), nullable=False),
        sa.Column("workflow_path", sa.String(), nullable=False),
        sa.Column("workflow_revision", sa.String(), nullable=True),
        sa.Column("workflow_attestation", sa.String(), nullable=False),
        sa.Column("rollout_job", sa.String(), nullable=True),
        sa.Column("rollout_job_conclusion", sa.String(), nullable=True),
        sa.Column("trigger_step", sa.String(), nullable=True),
        sa.Column("trigger_step_conclusion", sa.String(), nullable=True),
        sa.Column("concurrent_run_id", sa.BigInteger(), nullable=True),
        # BigInteger, not Integer. GitHub run ids passed 2^31 long ago — 31426195637 is this
        # repository's own most recent rollout — so Integer overflows on Postgres and is accepted
        # by SQLite, which is the half of the estate the test suite can see.
        sa.Column("run_id", sa.BigInteger(), nullable=True),
        sa.Column("run_attempt", sa.Integer(), nullable=True),
        sa.Column("run_url", sa.String(), nullable=True),
        sa.Column("run_conclusion", sa.String(), nullable=True),
        sa.Column("run_concluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_by", sa.String(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_deploy_observations_item_id", "deploy_observations", ["item_id"], unique=False
    )
    # The idempotency key. Unique in the SCHEMA rather than only in the service, so two watchers
    # racing on one run attempt collide in the database and the loser replays — the service's
    # IntegrityError branch has nothing to catch if this constraint is only a convention.
    op.create_index(
        "ix_deploy_observations_observation_key",
        "deploy_observations",
        ["observation_key"],
        unique=True,
    )
    op.create_index(
        "ix_deploy_observations_verdict", "deploy_observations", ["verdict"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_deploy_observations_verdict", table_name="deploy_observations")
    op.drop_index("ix_deploy_observations_observation_key", table_name="deploy_observations")
    op.drop_index("ix_deploy_observations_item_id", table_name="deploy_observations")
    op.drop_table("deploy_observations")
