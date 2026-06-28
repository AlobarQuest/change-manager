from datetime import UTC, datetime

import app.auth as auth
from app.models import ChangeEvent, ChangeItem

H = {"Authorization": "Bearer t"}
DEC = {"actor": "user:devon@x", "detail": "veritok secret rotated by hand"}


def _blocked(db) -> int:
    auth.settings.m2m_token = "t"
    it = ChangeItem(
        identity="prod::rotation::vt1", instance="prod", rule_key="rotation.secret",
        resource_uuid="vt1", resource_name="veritok", risk="caution", kind="question",
        reasoning="secret exposed", plan={}, status="blocked",
        first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
    )
    db.add(it)
    db.commit()
    return it.id


def test_resolve_blocked_item_sets_resolved_with_actor(client, db):
    iid = _blocked(db)
    r = client.post(f"/api/items/{iid}/resolve", json=DEC, headers=H)
    assert r.status_code == 200
    it = db.get(ChangeItem, iid)
    assert it.status == "resolved"
    assert it.decided_by == "user:devon@x"


def test_resolve_records_event_with_detail(client, db):
    iid = _blocked(db)
    client.post(f"/api/items/{iid}/resolve", json=DEC, headers=H)
    ev = db.query(ChangeEvent).filter_by(item_id=iid, event_type="resolved").one()
    assert ev.actor == "user:devon@x"
    assert ev.detail == "veritok secret rotated by hand"
    assert ev.to_status == "resolved"


def test_resolve_404_for_missing_item(client, db):
    auth.settings.m2m_token = "t"
    assert client.post("/api/items/9999/resolve", json=DEC, headers=H).status_code == 404
