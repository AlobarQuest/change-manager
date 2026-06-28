from datetime import UTC, datetime

import app.auth as auth
from app.models import ChangeItem

H = {"Authorization": "Bearer t"}


def _item(db, status="pending"):
    it = ChangeItem(
        identity=f"prod::hc::{status}",
        instance="prod",
        rule_key="coolify.enable_healthcheck",
        resource_uuid="u1",
        resource_name="o/app1:main",
        risk="safe",
        kind="remediation",
        reasoning="r",
        plan={"steps": []},
        status=status,
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        handoff_brief="# brief",
    )
    db.add(it)
    db.commit()
    return it


def test_api_handoff(client, db):
    auth.settings.m2m_token = "t"
    it = _item(db)
    r = client.post(f"/api/items/{it.id}/handoff", json={"actor": "devon@example.com"}, headers=H)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "handed_off"
    assert body["handoff_brief"] == "# brief"


def test_api_handoff_conflict_from_approved(client, db):
    auth.settings.m2m_token = "t"
    it = _item(db, status="approved")
    r = client.post(f"/api/items/{it.id}/handoff", json={"actor": "devon@example.com"}, headers=H)
    assert r.status_code == 409
