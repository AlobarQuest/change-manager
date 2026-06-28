from datetime import UTC, datetime

from app.models import ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest

NOW = datetime(2026, 6, 15, 3, 0, tzinfo=UTC)


def drift_esc(uuid="db1", rule="572"):
    return EscalationIn(
        proposal_id=f"{rule}:rand", instance="prod",
        target={"provider": "coolify", "resource_type": "database", "uuid": uuid, "name": "pg1"},
        risk="safe", kind="question", reasoning=f"rule #{rule}", plan={"root_cause": "x"}, note=None,
    )


def sec_esc(uuid="fp1", check="shell.plaintext_secret", urgent=True):
    return EscalationIn(
        proposal_id=f"sec.{check}:{uuid[:6]}", instance="mac",
        target={"provider": "security", "resource_type": "shell", "uuid": uuid, "name": "Inline secret"},
        risk="caution", kind="question",
        reasoning=f"[URGENT] {check} — /Users/x/.zshrc: TOKEN=<inline value>",
        plan={"tier": "URGENT", "source": "security"}, note=None, urgent=urgent,
    )


def drift_req(escalations):
    return SyncRequest(generated_at="2026-06-15T03:00:00Z", source_report="2026-06-15.remediation.json", escalations=escalations, source="drift")


def sec_req(escalations):
    return SyncRequest(generated_at="2026-06-15T03:00:00Z", source_report="2026-06-15.security.json", escalations=escalations, source="security")


def test_security_sync_does_not_resolve_drift_items(db):
    # seed a drift item
    reconcile(db, drift_req([drift_esc()]))
    # a security sync arrives with only security items
    reconcile(db, sec_req([sec_esc()]))
    drift = db.query(ChangeItem).filter_by(source="drift").one()
    assert drift.status == "pending"  # NOT resolved by the security sync
    sec = db.query(ChangeItem).filter_by(source="security").one()
    assert sec.status == "pending"
    assert sec.urgent is True


def test_drift_sync_does_not_resolve_security_items(db):
    reconcile(db, sec_req([sec_esc()]))
    reconcile(db, drift_req([drift_esc()]))
    sec = db.query(ChangeItem).filter_by(source="security").one()
    assert sec.status == "pending"  # NOT resolved by the drift sync


def test_security_item_resolves_when_absent_from_its_own_source_sync(db):
    reconcile(db, sec_req([sec_esc()]))
    reconcile(db, sec_req([]))  # security drift cleared
    sec = db.query(ChangeItem).filter_by(source="security").one()
    assert sec.status == "resolved"


def test_urgent_derived_from_reasoning_prefix_when_flag_absent(db):
    e = sec_esc(urgent=False)  # flag false, but reasoning starts with [URGENT]
    reconcile(db, sec_req([e]))
    assert db.query(ChangeItem).filter_by(source="security").one().urgent is True


def test_source_defaults_to_drift_for_legacy_payloads(db):
    # SyncRequest without an explicit source → "drift"
    legacy = SyncRequest(generated_at="2026-06-15T03:00:00Z", source_report="x.json", escalations=[drift_esc()])
    assert legacy.source == "drift"
    reconcile(db, legacy)
    assert db.query(ChangeItem).one().source == "drift"


def rot_esc(uuid="dk1"):
    return EscalationIn(
        proposal_id=f"rotation:{uuid}", instance="prod",
        target={"provider": "coolify", "resource_type": "application", "uuid": uuid, "name": "bookingapp"},
        risk="caution", kind="question",
        reasoning="deploy key exposed via coolify_get_deployment (pre-redaction)",
        plan={"steps": ["rotate"]}, note=None,
    )


def rot_req(escalations):
    return SyncRequest(
        generated_at="2026-06-18T03:00:00Z", source_report="rotation-scan-2026-06-18.json",
        escalations=escalations, source="rotation",
    )


def test_rotation_sync_creates_rotation_item(db):
    reconcile(db, rot_req([rot_esc()]))
    it = db.query(ChangeItem).filter_by(source="rotation").one()
    assert it.status == "pending"
    assert it.identity == "prod::rotation::dk1"
    assert it.risk == "caution"


def test_rotation_sync_does_not_resolve_drift_or_security(db):
    reconcile(db, drift_req([drift_esc()]))
    reconcile(db, sec_req([sec_esc()]))
    reconcile(db, rot_req([rot_esc()]))   # rotation batch with no drift/security items
    assert db.query(ChangeItem).filter_by(source="drift").one().status == "pending"
    assert db.query(ChangeItem).filter_by(source="security").one().status == "pending"


def test_rotation_item_resolves_when_absent_from_its_own_sync(db):
    reconcile(db, rot_req([rot_esc()]))
    reconcile(db, rot_req([]))            # the cred was rotated / no longer reported
    assert db.query(ChangeItem).filter_by(source="rotation").one().status == "resolved"
