from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register tables)
from app.db import Base


def test_change_items_has_handoff_columns():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("change_items")}
    assert "handoff_brief" in cols
    assert "handed_off_at" in cols
