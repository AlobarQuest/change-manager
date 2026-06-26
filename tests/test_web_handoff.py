import app.web_auth as wa
from app.models import ChangeItem
from datetime import datetime, timezone

SSO = {"X-authentik-email": "devon@x"}


def _item(db, status="pending"):
    it = ChangeItem(identity=f"prod::hc::{status}", instance="prod",
                    rule_key="coolify.enable_healthcheck", resource_uuid="u1",
                    resource_name="o/app1:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status,
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    handoff_brief="# brief")
    db.add(it); db.commit(); return it


def test_web_handoff_action(client, db):
    wa.settings.dev_user = ""
    it = _item(db)
    r = client.post(f"/items/{it.id}/handoff", headers=SSO)
    assert r.status_code == 200
    db.refresh(it)
    assert it.status == "handed_off"
    assert it.decided_by  # the SSO/dev user
