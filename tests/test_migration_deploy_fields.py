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


def _alembic(db: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def _migrated_columns() -> dict[str, int]:
    """name -> notnull flag, from a database built by the migrations alone."""
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "m.db")
        out = _alembic(db, "upgrade", "head")
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


def test_downgrade_keeps_the_record_and_its_history_and_parks_it():
    """The rollback path, exercised with a deploy record present.

    This suite is SQLite, where foreign keys are OFF — so a downgrade that violates
    one passes here and fails on production Postgres. Asserting on the OUTCOME rather
    than on FK enforcement makes the test discriminate anyway: the original
    `DELETE FROM change_items WHERE source = 'deploy'` leaves an orphaned `proposed`
    event behind (and SQLite then reuses the id, re-attaching that event to an
    unrelated item), which is what these assertions catch.

    Postgres itself is covered out of band — see the build report; the same downgrade
    with the DELETE is rc=1 there with a ForeignKeyViolation, and rc=0 without it.
    """
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "m.db")
        assert _alembic(db, "upgrade", "head").returncode == 0
        con = sqlite3.connect(db)
        con.execute(
            "INSERT INTO change_items (identity,instance,rule_key,risk,kind,reasoning,plan,"
            "status,source,urgent,first_seen_at,last_seen_at,lane,target_repository,"
            "pull_request_number) VALUES ('deploy::o/r::42','prod','deploying-merge','caution',"
            "'deploying_merge','r','{}','approved','deploy',0,'2026-08-10','2026-08-10',"
            "'deploy','o/r',42)"
        )
        con.execute(
            "INSERT INTO change_events (item_id,at,actor,event_type,to_status) "
            "VALUES (1,'2026-08-10','proposer','proposed','pending')"
        )
        con.commit()
        con.close()

        out = _alembic(db, "downgrade", "e3d4c5b6a7f8")
        assert out.returncode == 0, out.stderr

        con = sqlite3.connect(db)
        items = con.execute("SELECT id, source, status FROM change_items").fetchall()
        orphans = con.execute(
            "SELECT COUNT(*) FROM change_events e "
            "LEFT JOIN change_items i ON e.item_id = i.id WHERE i.id IS NULL"
        ).fetchone()[0]
        cols = {r[1] for r in con.execute("pragma table_info(change_items)").fetchall()}
        con.close()

    assert orphans == 0, "the downgrade destroyed an item its audit history still points at"
    assert items == [(1, "deploy", "wontfix")], (
        "the record must survive, parked — the previous build has none of this "
        "branch's guards and would let an approved deploy change be claimed"
    )
    assert not (_DEPLOY_COLUMNS & cols)
