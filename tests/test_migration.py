import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_alembic_upgrade_head_builds_schema():
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "m.db")
        env = {**os.environ, "DATABASE_URL": f"sqlite:///{db}"}
        out = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=env, cwd=str(REPO), capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
        names = {
            r[0]
            for r in sqlite3.connect(db)
            .execute("select name from sqlite_master where type='table'")
            .fetchall()
        }
        assert {"change_items", "change_attempts", "change_events", "window_runs"} <= names
        cols = {
            r[1]
            for r in sqlite3.connect(db).execute("pragma table_info(change_items)").fetchall()
        }
        assert {"source", "urgent"} <= cols
