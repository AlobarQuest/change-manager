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
