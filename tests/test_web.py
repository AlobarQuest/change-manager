import app.web_auth as wa
from app.models import ChangeItem

SSO = {"X-authentik-email": "devon@x"}
ESC = {"proposal_id": "571:r1", "instance": "prod",
       "target": {"provider": "coolify", "resource_type": "application", "uuid": "a1", "name": "app1"},
       "risk": "caution", "kind": "remediation", "reasoning": "needs https", "plan": {"root_cause": "x"},
       "note": None}
BODY = {"generated_at": "t", "source_report": "r.json", "escalations": [ESC]}
APIH = {"Authorization": "Bearer t"}


def _seed(client):
    import app.auth as auth
    auth.settings.m2m_token = "t"
    wa.settings.dev_user = ""
    client.post("/api/sync", json=BODY, headers=APIH)


def test_dashboard_requires_sso(client):
    _seed(client)
    assert client.get("/").status_code == 401


def test_dashboard_lists_items(client):
    _seed(client)
    r = client.get("/", headers=SSO)
    assert r.status_code == 200
    assert "app1" in r.text
    assert "needs https" in r.text


def test_item_detail_shows_plan_and_history(client, db):
    _seed(client)
    iid = db.query(ChangeItem).one().id
    r = client.get(f"/items/{iid}", headers=SSO)
    assert r.status_code == 200
    assert "needs https" in r.text          # reasoning
    assert "ingested" in r.text             # the sync event in the history timeline


def test_item_detail_404(client):
    _seed(client)
    assert client.get("/items/9999", headers=SSO).status_code == 404


from app.models import ChangeEvent


def test_approve_action_transitions_and_records_sso_user(client, db):
    _seed(client)
    iid = db.query(ChangeItem).one().id
    r = client.post(f"/items/{iid}/approve", headers=SSO)
    assert r.status_code == 200
    assert f'id="item-{iid}"' in r.text              # returns the swapped row fragment
    it = db.get(ChangeItem, iid)
    assert it.status == "approved"
    assert it.decided_by == "devon@x"                 # the SSO email
    assert db.query(ChangeEvent).filter_by(item_id=iid, event_type="approved").count() == 1


def test_wontfix_then_reactivate_via_gui(client, db):
    _seed(client)
    iid = db.query(ChangeItem).one().id
    client.post(f"/items/{iid}/wontfix", headers=SSO)
    assert db.get(ChangeItem, iid).status == "wontfix"
    r = client.post(f"/items/{iid}/reactivate", headers=SSO)
    assert r.status_code == 200
    assert db.get(ChangeItem, iid).status == "pending"


def test_unknown_action_is_400(client, db):
    _seed(client)
    iid = db.query(ChangeItem).one().id
    assert client.post(f"/items/{iid}/bogus", headers=SSO).status_code == 400


def test_reactivate_non_wontfix_is_409(client, db):
    _seed(client)
    iid = db.query(ChangeItem).one().id  # pending
    assert client.post(f"/items/{iid}/reactivate", headers=SSO).status_code == 409
