from datetime import UTC, datetime, timedelta

from app.models import ChangeEvent, ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn
from app.watchdog import revert_stale_handoffs


def _item(db, *, identity, handed_days_ago, status="handed_off", source="drift"):
    now = datetime.now(UTC)
    it = ChangeItem(
        identity=identity,
        instance="prod",
        rule_key="coolify.enable_healthcheck",
        resource_uuid=identity,
        resource_name="o/app1:main",
        risk="safe",
        kind="remediation",
        reasoning="r",
        plan={"steps": []},
        status=status,
        source=source,
        first_seen_at=now,
        last_seen_at=now,
        handoff_brief="# brief",
        handed_off_at=now - timedelta(days=handed_days_ago),
    )
    db.add(it)
    db.commit()
    return it


def test_stale_present_handoff_reverts_to_pending(db):
    it = _item(db, identity="i1", handed_days_ago=10)
    n = revert_stale_handoffs(
        db, now=datetime.now(UTC), source="drift", seen_identities={"i1"}, max_age_days=7
    )
    db.refresh(it)
    assert n == 1 and it.status == "pending"
    assert it.decided_by is None and it.decided_at is None
    ev = db.query(ChangeEvent).filter_by(item_id=it.id).one()
    assert ev.event_type == "handoff_watchdog_reverted"
    assert ev.from_status == "handed_off" and ev.to_status == "pending"


def test_fresh_handoff_is_left_alone(db):
    it = _item(db, identity="i2", handed_days_ago=2)
    n = revert_stale_handoffs(
        db, now=datetime.now(UTC), source="drift", seen_identities={"i2"}, max_age_days=7
    )
    db.refresh(it)
    assert n == 0 and it.status == "handed_off"


def test_stale_but_absent_is_not_reverted(db):
    # absent (not in seen_identities) → reconcile's resolve pass owns it, watchdog skips
    it = _item(db, identity="i3", handed_days_ago=10)
    n = revert_stale_handoffs(
        db, now=datetime.now(UTC), source="drift", seen_identities=set(), max_age_days=7
    )
    db.refresh(it)
    assert n == 0 and it.status == "handed_off"


def test_watchdog_is_source_scoped(db):
    it = _item(db, identity="i4", handed_days_ago=10, source="security")
    n = revert_stale_handoffs(
        db, now=datetime.now(UTC), source="drift", seen_identities={"i4"}, max_age_days=7
    )
    db.refresh(it)
    assert n == 0 and it.status == "handed_off"


def _esc(uuid="i1"):
    return EscalationIn(
        proposal_id=f"coolify.enable_healthcheck:{uuid}",
        instance="prod",
        target=TargetIn(
            provider="coolify", resource_type="application", uuid=uuid, name="o/app1:main"
        ),
        risk="safe",
        kind="remediation",
        reasoning="r",
        plan={"steps": []},
    )


def test_reconcile_runs_watchdog(db, monkeypatch):
    from app import reconcile as rec

    monkeypatch.setattr(rec.settings, "handoff_watchdog_days", 7, raising=False)
    # identity = stable_identity("prod", rule_key_of("coolify.enable_healthcheck:i1"), "i1")
    it = _item(db, identity="prod::coolify.enable_healthcheck::i1", handed_days_ago=10)
    reconcile(
        db,
        SyncRequest(
            generated_at="t", source_report="r.json", source="drift", escalations=[_esc("i1")]
        ),
    )
    db.refresh(it)
    assert it.status == "pending"  # still flagged + stale → watchdog reverted it
