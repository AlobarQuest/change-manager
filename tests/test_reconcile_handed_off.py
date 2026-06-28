# tests/test_reconcile_handed_off.py
from datetime import UTC, datetime

from app.models import ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn


def _seed(db, status="handed_off"):
    it = ChangeItem(identity="prod::coolify.enable_healthcheck::u1", instance="prod",
                    rule_key="coolify.enable_healthcheck", resource_uuid="u1",
                    resource_name="o/app1:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status, source="drift",
                    first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
                    handoff_brief="# brief", handed_off_at=datetime.now(UTC))
    db.add(it); db.commit(); return it


def _esc():
    return EscalationIn(proposal_id="coolify.enable_healthcheck:app1", instance="prod",
                        target=TargetIn(provider="coolify", resource_type="application", uuid="u1", name="o/app1:main"),
                        risk="safe", kind="remediation", reasoning="r", plan={"steps": []})


def _req(escs):
    return SyncRequest(generated_at="t", source_report="r.json", source="drift", escalations=escs)


def test_handed_off_resolves_when_absent(db):
    _seed(db)
    reconcile(db, _req([]))  # finding cleared (app conformed)
    assert db.query(ChangeItem).one().status == "resolved"


def test_handed_off_stays_when_still_present(db):
    _seed(db)
    reconcile(db, _req([_esc()]))  # still flagged, recently handed off
    assert db.query(ChangeItem).one().status == "handed_off"
