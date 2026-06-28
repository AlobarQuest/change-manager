from datetime import UTC, datetime

from app.events import record_event
from app.models import ChangeEvent, ChangeItem


def _item(db):
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
        status="pending",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    db.add(it)
    db.flush()
    return it


def test_record_event_appends_a_row_with_transition(db):
    it = _item(db)
    record_event(
        db,
        it,
        actor="user:devon@x",
        event_type="approved",
        from_status="pending",
        to_status="approved",
        detail="approved",
    )
    db.commit()
    ev = db.query(ChangeEvent).one()
    assert ev.item_id == it.id
    assert ev.actor == "user:devon@x"
    assert ev.event_type == "approved"
    assert (ev.from_status, ev.to_status) == ("pending", "approved")
    assert ev.at is not None
