from datetime import UTC, datetime

from app.models import ChangeAttempt, ChangeEvent, ChangeItem, WindowRun


def test_change_item_roundtrips(db):
    item = ChangeItem(
        identity="prod::572::db1",
        instance="prod",
        rule_key="572",
        resource_uuid="db1",
        resource_name="pg1",
        risk="safe",
        kind="question",
        reasoning="rule #572",
        plan={"root_cause": "x"},
        status="pending",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    got = db.query(ChangeItem).filter_by(identity="prod::572::db1").one()
    assert got.status == "pending"
    assert got.plan["root_cause"] == "x"


def test_related_rows_link_to_item(db):
    item = ChangeItem(
        identity="prod::571::a1",
        instance="prod",
        rule_key="571",
        resource_uuid="a1",
        resource_name="app1",
        risk="caution",
        kind="remediation",
        reasoning="r",
        plan={},
        status="approved",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    db.add(item)
    db.flush()
    db.add(
        ChangeEvent(
            item_id=item.id,
            at=datetime.now(UTC),
            actor="sync",
            event_type="ingested",
            to_status="pending",
        )
    )
    db.add(ChangeAttempt(item_id=item.id, started_at=datetime.now(UTC), outcome="done"))
    db.add(WindowRun(started_at=datetime.now(UTC), status="running"))
    db.commit()
    assert db.query(ChangeEvent).count() == 1
    assert db.query(ChangeAttempt).count() == 1
    assert db.query(WindowRun).count() == 1
