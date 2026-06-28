from app.models import ChangeItem
from app.reconcile import reconcile
from app.schemas import EscalationIn, SyncRequest, TargetIn


def _esc(brief=None, lane="infra-config"):
    return EscalationIn(
        proposal_id="coolify.enable_healthcheck:app1",
        instance="prod",
        target=TargetIn(
            provider="coolify", resource_type="application", uuid="u1", name="o/app1:main"
        ),
        risk="safe",
        kind="remediation",
        reasoning="health check missing",
        plan={"steps": ["x"]},
        lane=lane,
        handoff_brief=brief,
    )


def _req(escs):
    return SyncRequest(generated_at="t", source_report="r.json", source="drift", escalations=escs)


def test_sync_persists_handoff_brief(db):
    reconcile(db, _req([_esc(brief="# brief body", lane="app-conformance")]))
    it = db.query(ChangeItem).one()
    assert it.handoff_brief == "# brief body"
    assert it.status == "pending"  # ingested as pending; human hands off


def test_sync_without_brief_leaves_it_null(db):
    reconcile(db, _req([_esc()]))
    assert db.query(ChangeItem).one().handoff_brief is None


def test_resync_refreshes_brief(db):
    reconcile(db, _req([_esc(brief="v1", lane="app-conformance")]))
    reconcile(db, _req([_esc(brief="v2", lane="app-conformance")]))
    assert db.query(ChangeItem).one().handoff_brief == "v2"
