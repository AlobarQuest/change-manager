# tests/test_web_handoff_gui_refine.py
from datetime import datetime, timezone
import app.web_auth as wa
from app.models import ChangeItem


def setup_module(module):
    wa.settings.dev_user = "test@dev"


def teardown_module(module):
    wa.settings.dev_user = ""


def _item(db, *, lane="app-conformance", brief="# Handoff brief\nadd /api/health", pr_url=None):
    it = ChangeItem(identity="prod::hc::u1", instance="prod", rule_key="coolify.enable_healthcheck",
                    resource_uuid="u1", resource_name="o/booking-system:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status="pending", source="drift",
                    first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
                    lane=lane, handoff_brief=brief, pr_url=pr_url)
    db.add(it); db.commit(); return it


def test_detail_has_copy_button_and_lane_badge(client, db):
    it = _item(db)
    html = client.get(f"/items/{it.id}").text
    assert "Copy brief" in html
    assert "app-conformance" in html          # lane badge
    assert "add /api/health" in html          # brief text rendered
    assert "DISPATCH SEAM" in html            # documented Phase-2 seam (HTML comment)


def test_detail_shows_pr_url_when_set(client, db):
    it = _item(db, pr_url="https://github.com/x/y/pull/27")
    html = client.get(f"/items/{it.id}").text
    assert "https://github.com/x/y/pull/27" in html
