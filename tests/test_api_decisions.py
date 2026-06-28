import app.auth as auth
from app.models import ChangeEvent, ChangeItem

H = {"Authorization": "Bearer t"}
ESC = {
    "proposal_id": "571:r1",
    "instance": "prod",
    "target": {"provider": "coolify", "resource_type": "application", "uuid": "a1", "name": "app1"},
    "risk": "caution",
    "kind": "remediation",
    "reasoning": "r",
    "plan": {},
    "note": None,
}
BODY = {"generated_at": "t", "source_report": "r.json", "escalations": [ESC]}
DEC = {"actor": "user:devon@x"}


def _pending(client, db):
    auth.settings.m2m_token = "t"
    client.post("/api/sync", json=BODY, headers=H)
    return db.query(ChangeItem).one().id


def test_approve_sets_approved_with_decider(client, db):
    iid = _pending(client, db)
    assert client.post(f"/api/items/{iid}/approve", json=DEC, headers=H).status_code == 200
    it = db.get(ChangeItem, iid)
    assert it.status == "approved"
    assert it.decided_by == "user:devon@x"
    assert db.query(ChangeEvent).filter_by(item_id=iid, event_type="approved").count() == 1


def test_defer_and_wontfix(client, db):
    iid = _pending(client, db)
    client.post(f"/api/items/{iid}/defer", json=DEC, headers=H)
    assert db.get(ChangeItem, iid).status == "deferred"
    client.post(f"/api/items/{iid}/wontfix", json=DEC, headers=H)
    assert db.get(ChangeItem, iid).status == "wontfix"


def test_reactivate_only_from_wontfix(client, db):
    iid = _pending(client, db)
    assert client.post(f"/api/items/{iid}/reactivate", json=DEC, headers=H).status_code == 409
    client.post(f"/api/items/{iid}/wontfix", json=DEC, headers=H)
    assert client.post(f"/api/items/{iid}/reactivate", json=DEC, headers=H).status_code == 200
    it = db.get(ChangeItem, iid)
    assert it.status == "pending"
    assert db.query(ChangeEvent).filter_by(item_id=iid, event_type="reactivated").count() == 1
