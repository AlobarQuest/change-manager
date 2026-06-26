from datetime import datetime, timezone

import app.web_auth as wa
from app.models import ChangeItem


def setup_module(module):
    """Enable dev-user bypass so these GUI tests don't need SSO headers."""
    wa.settings.dev_user = "test@dev"


def teardown_module(module):
    wa.settings.dev_user = ""


def _item(db, status="pending", brief="# Handoff brief\nDo the thing"):
    it = ChangeItem(identity=f"prod::hc::{status}", instance="prod",
                    rule_key="coolify.enable_healthcheck", resource_uuid="u1",
                    resource_name="o/app1:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status,
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    handoff_brief=brief)
    db.add(it); db.commit(); return it


def test_dashboard_has_handed_off_tab(client, db):
    r = client.get("/?status=handed_off")
    assert r.status_code == 200
    assert "handed_off" in r.text


def test_row_shows_handoff_button_for_brief_item(client, db):
    it = _item(db, status="pending")
    r = client.get("/?status=pending")
    assert f"/items/{it.id}/handoff" in r.text


def test_row_hides_handoff_button_without_brief(client, db):
    it = _item(db, status="pending", brief=None)
    r = client.get("/?status=pending")
    assert f"/items/{it.id}/handoff" not in r.text


def test_detail_renders_brief(client, db):
    it = _item(db)
    r = client.get(f"/items/{it.id}")
    assert "Handoff brief" in r.text
    assert "Do the thing" in r.text
