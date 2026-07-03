from datetime import UTC, datetime

import app.auth as auth
from app.events import record_event
from app.models import ChangeItem

H = {"Authorization": "Bearer t"}


def _seed(db, n: int) -> ChangeItem:
    now = datetime.now(UTC)
    item = ChangeItem(
        identity=f"it-{n}",
        instance="prod",
        rule_key="backup.configured",
        resource_type="database",
        resource_uuid=f"u-{n}",
        resource_name=f"db-{n}",
        risk="low",
        kind="config",
        status="pending",
        source="drift",
        reasoning="r",
        plan={},
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(item)
    db.flush()
    record_event(db, item, actor="sync", event_type="created", to_status="pending")
    record_event(
        db,
        item,
        actor="devon@example.com",
        event_type="approved",
        from_status="pending",
        to_status="approved",
    )
    db.commit()
    return item


def test_events_pagination_and_shape(client, db):
    auth.settings.m2m_token = "t"
    _seed(db, 1)
    r = client.get("/api/events?after_id=0&limit=1", headers=H)
    assert r.status_code == 200
    events = r.json()["events"]
    assert len(events) == 1
    first = events[0]
    assert first["event_type"] == "created" and first["item_identity"] == "it-1"
    assert first["item_rule_key"] == "backup.configured" and first["item_instance"] == "prod"
    r2 = client.get(f"/api/events?after_id={first['id']}&limit=100", headers=H)
    rest = r2.json()["events"]
    assert [e["event_type"] for e in rest] == ["approved"]
    r3 = client.get(f"/api/events?after_id={rest[-1]['id']}", headers=H)
    assert r3.json()["events"] == []


def test_events_requires_m2m(client, db):
    auth.settings.m2m_token = "t"
    assert client.get("/api/events").status_code == 401
