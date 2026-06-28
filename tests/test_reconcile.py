from datetime import UTC, datetime

from app.models import ChangeEvent, ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn

NOW = datetime(2026, 6, 14, 7, 0, tzinfo=UTC)


def esc(uuid="db1", rule="572", instance="prod", name="pg1"):
    return EscalationIn(
        proposal_id=f"{rule}:rand",
        instance=instance,
        target=TargetIn(provider="coolify", resource_type="database", uuid=uuid, name=name),
        risk="safe",
        kind="question",
        reasoning=f"rule #{rule}",
        plan={"root_cause": "x"},
        note=None,
    )


def req(escalations):
    return SyncRequest(
        generated_at="2026-06-14T07:00:00Z",
        source_report="2026-06-14.json",
        escalations=escalations,
    )


def _item(db, identity, status):
    it = ChangeItem(
        identity=identity,
        instance="prod",
        rule_key="572",
        resource_uuid="db1",
        resource_name="pg1",
        risk="safe",
        kind="question",
        reasoning="r",
        plan={},
        status=status,
        first_seen_at=NOW,
        last_seen_at=NOW,
    )
    db.add(it)
    db.commit()
    return it


def test_new_escalation_inserts_pending_with_event(db):
    s = reconcile(db, req([esc()]))
    assert s.new == 1 and s.refreshed == 0
    it = db.query(ChangeItem).filter_by(identity="prod::572::db1").one()
    assert it.status == "pending"
    assert db.query(ChangeEvent).filter_by(item_id=it.id, event_type="ingested").count() == 1


def test_existing_pending_is_refreshed_not_duplicated(db):
    _item(db, "prod::572::db1", "approved")
    s = reconcile(db, req([esc()]))
    assert s.new == 0 and s.refreshed == 1
    assert db.query(ChangeItem).count() == 1
    assert db.query(ChangeItem).one().status == "approved"  # decision preserved


def test_done_item_reappearing_reopens_to_pending(db):
    _item(db, "prod::572::db1", "done")
    s = reconcile(db, req([esc()]))
    assert s.reopened == 1
    it = db.query(ChangeItem).one()
    assert it.status == "pending"
    assert (
        db.query(ChangeEvent).filter_by(item_id=it.id, event_type="regression_reopened").count()
        == 1
    )


def test_wontfix_survives_sync(db):
    _item(db, "prod::572::db1", "wontfix")
    reconcile(db, req([esc()]))
    assert db.query(ChangeItem).one().status == "wontfix"


def test_item_absent_from_report_resolves(db):
    _item(db, "prod::572::db1", "approved")
    s = reconcile(db, req([]))  # no escalations this run
    assert s.resolved == 1
    it = db.query(ChangeItem).one()
    assert it.status == "resolved"
    assert db.query(ChangeEvent).filter_by(item_id=it.id, event_type="resolved").count() == 1


def test_absent_wontfix_is_not_resolved(db):
    _item(db, "prod::572::db1", "wontfix")
    s = reconcile(db, req([]))
    assert s.resolved == 0
    assert db.query(ChangeItem).one().status == "wontfix"


def test_decided_by_cleared_on_reopen(db):
    it = _item(db, "prod::572::db1", "done")
    it.decided_by = "alice"
    it.decided_at = NOW
    db.commit()
    reconcile(db, req([esc()]))
    it = db.query(ChangeItem).one()
    assert it.decided_by is None
    assert it.decided_at is None
