import app.auth as auth
from app.models import ChangeAttempt, ChangeEvent, ChangeItem

H = {"Authorization": "Bearer t"}
ESC = {
    "proposal_id": "571:r1",
    "instance": "prod",
    "target": {"provider": "coolify", "resource_type": "application", "uuid": "a1", "name": "app1"},
    "risk": "caution",
    "kind": "remediation",
    "reasoning": "rule #571",
    "plan": {"root_cause": "x"},
    "note": None,
}
BODY = {"generated_at": "t", "source_report": "2026-06-14.json", "escalations": [ESC]}


def _approved(client, db):
    auth.settings.m2m_token = "t"
    client.post("/api/sync", json=BODY, headers=H)
    it = db.query(ChangeItem).one()
    it.status = "approved"
    db.commit()
    return it.id


def test_claim_flips_approved_to_in_progress_then_409_on_second(client, db):
    iid = _approved(client, db)
    assert client.post(f"/api/items/{iid}/claim", headers=H).status_code == 200
    assert db.get(ChangeItem, iid).status == "in_progress"
    assert client.post(f"/api/items/{iid}/claim", headers=H).status_code == 409


def test_outcome_records_attempt_and_transitions(client, db):
    iid = _approved(client, db)
    client.post(f"/api/items/{iid}/claim", headers=H)
    r = client.post(
        f"/api/items/{iid}/outcome",
        headers=H,
        json={"outcome": "done", "detail": "applied", "tool_calls": {"calls": []}},
    )
    assert r.status_code == 200
    assert db.get(ChangeItem, iid).status == "done"
    assert db.query(ChangeAttempt).filter_by(item_id=iid).count() == 1
    assert db.query(ChangeEvent).filter_by(item_id=iid, event_type="attempt_done").count() == 1


def test_outcome_blocked_sets_blocked(client, db):
    iid = _approved(client, db)
    client.post(f"/api/items/{iid}/claim", headers=H)
    client.post(
        f"/api/items/{iid}/outcome", headers=H, json={"outcome": "blocked", "detail": "no S3"}
    )
    assert db.get(ChangeItem, iid).status == "blocked"
