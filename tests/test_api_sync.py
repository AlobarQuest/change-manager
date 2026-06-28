import app.auth as auth

ESC = {
    "proposal_id": "572:r1",
    "instance": "prod",
    "target": {"provider": "coolify", "resource_type": "database", "uuid": "db1", "name": "pg1"},
    "risk": "safe",
    "kind": "question",
    "reasoning": "rule #572",
    "plan": {"root_cause": "x"},
    "note": None,
}
BODY = {
    "generated_at": "2026-06-14T07:00:00Z",
    "source_report": "2026-06-14.json",
    "escalations": [ESC],
}
H = {"Authorization": "Bearer testtok"}


def _auth():
    auth.settings.m2m_token = "testtok"


def test_sync_then_list_and_get(client):
    _auth()
    r = client.post("/api/sync", json=BODY, headers=H)
    assert r.status_code == 200
    assert r.json() == {"new": 1, "refreshed": 0, "resolved": 0, "reopened": 0}

    lst = client.get("/api/items", headers=H).json()
    assert len(lst) == 1
    item_id = lst[0]["id"]
    assert lst[0]["status"] == "pending"
    assert lst[0]["instance"] == "prod"

    one = client.get(f"/api/items/{item_id}", headers=H).json()
    assert one["resource_name"] == "pg1"
    assert one["plan"]["root_cause"] == "x"


def test_sync_requires_auth(client):
    _auth()
    assert client.post("/api/sync", json=BODY).status_code == 401


def test_list_filters_by_status(client):
    _auth()
    client.post("/api/sync", json=BODY, headers=H)
    assert len(client.get("/api/items?status=pending", headers=H).json()) == 1
    assert len(client.get("/api/items?status=approved", headers=H).json()) == 0
