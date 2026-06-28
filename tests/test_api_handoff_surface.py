from datetime import UTC, datetime

import app.auth as auth
from app.models import ChangeItem

HANDOFF = {"repo": "booking-system", "target_branch": "main", "rule": "coolify.enable_healthcheck",
           "verified_gap": "g", "required_change": "c", "acceptance_check": "GET … 2xx",
           "scope_guard": "app only", "do_nots": ["a", "b"]}


def setup_module(module):
    auth.settings.m2m_token = "t"


def _hdr():
    return {"Authorization": "Bearer t"}


def _item(db, *, lane="app-conformance", handoff=HANDOFF, status="pending", uuid="u1"):
    it = ChangeItem(identity=f"prod::hc::{uuid}", instance="prod", rule_key="coolify.enable_healthcheck",
                    resource_uuid=uuid, resource_name="o/booking-system:main", risk="safe", kind="remediation",
                    reasoning="r", plan={"steps": []}, status=status, source="drift",
                    first_seen_at=datetime.now(UTC), last_seen_at=datetime.now(UTC),
                    lane=lane, handoff=handoff, handoff_brief="# brief")
    db.add(it); db.commit(); return it


def test_list_filter_by_lane(client, db):
    _item(db, lane="app-conformance", uuid="u1")
    _item(db, lane="infra-config", handoff=None, uuid="u2")
    rows = client.get("/api/items?lane=app-conformance", headers=_hdr()).json()
    assert [r["resource_uuid"] for r in rows] == ["u1"]
    assert rows[0]["lane"] == "app-conformance"
    assert rows[0]["handoff"] == HANDOFF


def test_get_handoff_package(client, db):
    it = _item(db)
    body = client.get(f"/api/items/{it.id}/handoff", headers=_hdr()).json()
    assert body["item_id"] == it.id
    assert body["repo"] == "booking-system"
    assert body["do_nots"] == ["a", "b"]
    assert body["pr_url"] is None


def test_get_handoff_404_when_no_handoff(client, db):
    it = _item(db, lane="infra-config", handoff=None)
    assert client.get(f"/api/items/{it.id}/handoff", headers=_hdr()).status_code == 404


def test_patch_pr_url(client, db):
    it = _item(db)
    r = client.patch(f"/api/items/{it.id}", json={"pr_url": "https://github.com/x/y/pull/27"}, headers=_hdr())
    assert r.status_code == 200
    assert r.json()["pr_url"] == "https://github.com/x/y/pull/27"
    db.refresh(it)
    assert it.pr_url == "https://github.com/x/y/pull/27"
