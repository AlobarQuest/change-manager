import app.auth as auth
from app.models import ChangeEvent, ChangeItem

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
BODY = {"generated_at": "t", "source_report": "2026-07-03.json", "escalations": [ESC]}


def _approved(client, db):
    auth.settings.m2m_token = "t"
    client.post("/api/sync", json=BODY, headers=H)
    it = db.query(ChangeItem).one()
    it.status = "approved"
    db.commit()
    return it.id


def test_claim_records_declared_actor(client, db):
    iid = _approved(client, db)
    r = client.post(f"/api/items/{iid}/claim", headers=H, json={"actor": "security-executor"})
    assert r.status_code == 200
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="claimed").one()
    assert ev.actor == "security-executor"


def test_claim_without_body_defaults_to_executor(client, db):
    iid = _approved(client, db)
    assert client.post(f"/api/items/{iid}/claim", headers=H).status_code == 200
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="claimed").one()
    assert ev.actor == "executor"


def test_outcome_records_declared_actor(client, db):
    iid = _approved(client, db)
    client.post(f"/api/items/{iid}/claim", headers=H, json={"actor": "change-window-agent"})
    r = client.post(
        f"/api/items/{iid}/outcome",
        headers=H,
        json={"outcome": "done", "detail": "applied", "actor": "change-window-agent"},
    )
    assert r.status_code == 200
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="attempt_done").one()
    assert ev.actor == "change-window-agent"


def test_outcome_without_actor_defaults_to_executor(client, db):
    iid = _approved(client, db)
    client.post(f"/api/items/{iid}/claim", headers=H)
    client.post(f"/api/items/{iid}/outcome", headers=H, json={"outcome": "done", "detail": "x"})
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="attempt_done").one()
    assert ev.actor == "executor"
