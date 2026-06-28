from app.models import ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn

HANDOFF = {
    "repo": "booking-system",
    "target_branch": "main",
    "rule": "coolify.enable_healthcheck",
    "verified_gap": "GET …/api/health → 404",
    "required_change": "add /api/health",
    "acceptance_check": "GET …/api/health returns 2xx",
    "scope_guard": "app repo only",
    "do_nots": ["don't hand-resolve", "don't touch Coolify"],
}


def _esc(lane="app-conformance", handoff=HANDOFF, brief: str | None = "# brief"):
    return EscalationIn(
        proposal_id="coolify.enable_healthcheck:app1",
        instance="prod",
        target=TargetIn(
            provider="coolify", resource_type="application", uuid="u1", name="o/booking-system:main"
        ),
        risk="safe",
        kind="remediation",
        reasoning="health check missing",
        plan={"steps": ["x"]},
        lane=lane,
        handoff=handoff,
        handoff_brief=brief,
    )


def _req(escs):
    return SyncRequest(generated_at="t", source_report="r.json", source="drift", escalations=escs)


def test_sync_persists_lane_and_structured_handoff(db):
    reconcile(db, _req([_esc()]))
    it = db.query(ChangeItem).one()
    assert it.lane == "app-conformance"
    assert it.handoff == HANDOFF
    assert it.handoff_brief == "# brief"


def test_sync_defaults_lane_infra_config(db):
    reconcile(db, _req([_esc(lane="infra-config", handoff=None, brief=None)]))
    it = db.query(ChangeItem).one()
    assert it.lane == "infra-config"
    assert it.handoff is None


def test_resync_refreshes_lane_and_handoff(db):
    reconcile(db, _req([_esc()]))
    updated = {**HANDOFF, "verified_gap": "v2"}
    reconcile(db, _req([_esc(handoff=updated)]))
    it = db.query(ChangeItem).one()
    assert it.handoff["verified_gap"] == "v2"
