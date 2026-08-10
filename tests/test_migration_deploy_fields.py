"""The deploy columns exist after `alembic upgrade head`, and the two
infrastructure-resource identifiers a proposal cannot supply are nullable there.

The model-level twin (`Base.metadata.create_all`) is what every other test runs
against, so on its own it proves nothing about the database `entrypoint.sh` migrates.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

_DEPLOY_COLUMNS = {
    "target_repository",
    "pull_request_number",
    "change_class",
    "acceptance_criteria",
    "rollback_plan",
}


def _migrated_columns() -> dict[str, int]:
    """name -> notnull flag, from a database built by the migrations alone."""
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "m.db")
        out = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
            cwd=str(REPO),
            capture_output=True,
            text=True,
        )
        assert out.returncode == 0, out.stderr
        rows = sqlite3.connect(db).execute("pragma table_info(change_items)").fetchall()
    return {r[1]: r[3] for r in rows}


def test_migrated_schema_carries_the_deploy_columns_and_relaxes_the_resource_ids():
    cols = _migrated_columns()
    assert _DEPLOY_COLUMNS <= set(cols)
    assert cols["resource_uuid"] == 0, "a proposal has no infrastructure resource uuid"
    assert cols["resource_name"] == 0, "a proposal has no infrastructure resource name"
    # Filled by the proposal route, so `GET /api/events` gains no new nulls.
    assert cols["instance"] == 1
    assert cols["rule_key"] == 1
