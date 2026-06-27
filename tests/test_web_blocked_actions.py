from datetime import datetime, timezone

import app.web_auth as wa
from app.models import ChangeEvent, ChangeItem


def setup_module(module):
    """Enable dev-user bypass so these GUI tests don't need SSO headers."""
    wa.settings.dev_user = "test@dev"


def teardown_module(module):
    wa.settings.dev_user = ""


def _blocked(db, brief=None):
    it = ChangeItem(
        identity="prod::rotation::vt1", instance="prod", rule_key="rotation.secret",
        resource_uuid="vt1", resource_name="veritok", risk="caution", kind="question",
        reasoning="secret exposed", plan={"steps": []}, status="blocked",
        first_seen_at=datetime.now(timezone.utc), last_seen_at=datetime.now(timezone.utc),
        handoff_brief=brief,
    )
    db.add(it)
    db.commit()
    return it


def test_row_offers_resolve_and_wontfix_on_blocked(client, db):
    it = _blocked(db)
    r = client.get("/?status=blocked")
    assert r.status_code == 200
    assert f"/items/{it.id}/resolve" in r.text
    assert f"/items/{it.id}/wontfix" in r.text


def test_row_does_not_offer_approve_on_blocked(client, db):
    it = _blocked(db)
    r = client.get("/?status=blocked")
    assert f"/items/{it.id}/approve" not in r.text


def test_detail_offers_resolve_and_wontfix_on_blocked(client, db):
    it = _blocked(db)
    r = client.get(f"/items/{it.id}")
    assert r.status_code == 200
    assert f"/items/{it.id}/resolve" in r.text
    assert f"/items/{it.id}/wontfix" in r.text


def test_resolve_action_via_gui_sets_resolved_and_records_actor(client, db):
    it = _blocked(db)
    r = client.post(f"/items/{it.id}/resolve", headers={"HX-Request": "true"})
    assert r.status_code == 200
    assert f'id="item-{it.id}"' in r.text
    db.refresh(it)
    assert it.status == "resolved"
    assert it.decided_by == "test@dev"
    assert db.query(ChangeEvent).filter_by(item_id=it.id, event_type="resolved").count() == 1


def test_wontfix_action_via_gui_works_on_blocked(client, db):
    it = _blocked(db)
    client.post(f"/items/{it.id}/wontfix", headers={"HX-Request": "true"})
    db.refresh(it)
    assert it.status == "wontfix"
