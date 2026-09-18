"""add the originating observation reference to change_items (the signal->work contract)

One nullable column on both proposed sources rather than a key in `plan`, for the reason
ADR-0019 gave for `acceptance_criteria` and ADR-0026 repeated for the package locator: the
value is something a record can be refused for, and a refusal needs a column to be absent from.

NO FOREIGN KEY, and none is available: the observation is a row in the orchestrator's database,
which this service has no egress to. Null means "nothing recorded a cause" and never "no cause
exists" -- every record proposed before this column existed carries null, and nothing back-fills
them.

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-09-18
"""

import sqlalchemy as sa

from alembic import op

revision = "3d4e5f6a7b8c"
down_revision = "2c3d4e5f6a7b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "change_items", sa.Column("originating_observation_id", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("change_items", "originating_observation_id")
