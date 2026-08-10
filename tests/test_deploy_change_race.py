"""Two proposals for one pull request, racing.

`propose_deploy_change` SELECTs and then INSERTs against a unique index, and its
docstring promises "a caller that lost our response can retry". That promise is worth
exactly nothing if the retry is what breaks it — so the interleaving is driven
deterministically rather than hoped for: a `before_flush` hook lets a second
connection commit the winning row after our SELECT has already missed.
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.db import Base
from app.deploy_changes import DeployChangeConflict, propose_deploy_change
from app.models import ChangeItem
from app.schemas import DeployChangeIn

PAYLOAD = {
    "target_repository": "AlobarQuest/change-manager",
    "pull_request_number": 42,
    "change_class": "dependency-update",
    "risk": "caution",
    "reasoning": "uvicorn floor bump",
    "acceptance_criteria": ["/api/health reports the merged commit"],
    "rollback_plan": {"steps": ["re-point the image tag", "revert"]},
    "actor": "test",
}


@pytest.fixture()
def file_engine():
    """A real file database — two connections are the point, so :memory: will not do."""
    with tempfile.TemporaryDirectory() as d:
        engine = create_engine(f"sqlite:///{Path(d) / 'race.db'}")
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


def _race(file_engine, loser_payload: dict, winner_payload: dict):
    """Run `propose_deploy_change(loser)` with `winner` committing mid-flush."""
    session = Session(file_engine)
    fired = []

    @event.listens_for(session, "before_flush")
    def _competitor(sess, flush_context, instances):
        if fired:
            return
        fired.append(True)
        with Session(file_engine) as other:
            propose_deploy_change(other, DeployChangeIn(**winner_payload))

    try:
        return propose_deploy_change(session, DeployChangeIn(**loser_payload)), fired
    finally:
        session.close()


def test_losing_the_race_with_an_identical_proposal_replays(file_engine):
    (item, created), fired = _race(file_engine, PAYLOAD, PAYLOAD)
    assert fired, "the competitor never ran — this test proved nothing"
    assert created is False
    with Session(file_engine) as s:
        rows = s.scalars(select(ChangeItem)).all()
        assert len(rows) == 1
        assert item.id == rows[0].id


def test_losing_the_race_with_a_divergent_proposal_still_conflicts(file_engine):
    """The retry path must not become a way to have a divergence accepted."""
    winner = {**PAYLOAD, "acceptance_criteria": ["something else entirely"]}
    with pytest.raises(DeployChangeConflict):
        _race(file_engine, PAYLOAD, winner)
    with Session(file_engine) as s:
        assert len(s.scalars(select(ChangeItem)).all()) == 1
