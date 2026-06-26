import pytest

from app.models import ChangeEvent, ChangeItem
from app.transitions import TransitionError, hand_off


def _item(db, status):
    it = ChangeItem(
        identity=f"prod::hc::{status}", instance="prod", rule_key="coolify.enable_healthcheck",
        resource_uuid="u1", resource_name="o/app1:main", risk="safe", kind="remediation",
        reasoning="r", plan={"steps": []}, status=status,
        first_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        last_seen_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        handoff_brief="# brief",
    )
    db.add(it); db.commit(); return it


def test_hand_off_from_pending(db):
    it = _item(db, "pending")
    hand_off(db, it, actor="devon@example.com")
    assert it.status == "handed_off"
    assert it.handed_off_at is not None
    assert it.decided_by == "devon@example.com"
    ev = db.query(ChangeEvent).filter_by(item_id=it.id).one()
    assert ev.event_type == "handed_off"
    assert ev.from_status == "pending" and ev.to_status == "handed_off"
    assert ev.actor == "devon@example.com"


def test_hand_off_from_blocked(db):
    it = _item(db, "blocked")
    hand_off(db, it, actor="devon@example.com")
    assert it.status == "handed_off"


def test_hand_off_rejects_other_status(db):
    it = _item(db, "approved")
    with pytest.raises(TransitionError):
        hand_off(db, it, actor="devon@example.com")
    assert it.status == "approved"
