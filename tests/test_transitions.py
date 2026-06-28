from datetime import UTC, datetime

import pytest

from app.models import ChangeEvent, ChangeItem
from app.transitions import TransitionError, decide, reactivate


def _item(db, status):
    it = ChangeItem(
        identity="prod::571::a1",
        instance="prod",
        rule_key="571",
        resource_uuid="a1",
        resource_name="app1",
        risk="caution",
        kind="remediation",
        reasoning="r",
        plan={},
        status=status,
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    db.add(it)
    db.flush()
    return it


def test_decide_sets_status_decider_and_event(db):
    it = _item(db, "pending")
    decide(db, it, actor="user:devon@x", new_status="approved", event_type="approved")
    assert it.status == "approved"
    assert it.decided_by == "user:devon@x"
    assert it.decided_at is not None
    assert db.query(ChangeEvent).filter_by(item_id=it.id, event_type="approved").count() == 1


def test_reactivate_requires_wontfix(db):
    it = _item(db, "pending")
    with pytest.raises(TransitionError):
        reactivate(db, it, actor="user:devon@x")


def test_reactivate_from_wontfix_goes_pending(db):
    it = _item(db, "wontfix")
    reactivate(db, it, actor="user:devon@x")
    assert it.status == "pending"
    assert db.query(ChangeEvent).filter_by(item_id=it.id, event_type="reactivated").count() == 1
