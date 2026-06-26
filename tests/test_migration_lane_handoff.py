from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool
from app.db import Base
import app.models  # noqa: F401


def test_change_items_has_lane_handoff_pr_url():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("change_items")}
    assert {"lane", "handoff", "pr_url"} <= cols
