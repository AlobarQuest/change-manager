"""POST /api/deploy-changes — the ingress that proposes rather than derives.

The refusals are the substance. ADR-0019 records acceptance criteria and a rollback
plan so that a deploying change can be REFUSED for lacking them; a field that may be
an empty string is a field that will be.
"""

import pytest

from app.models import ChangeItem


def test_a_well_formed_proposal_is_created(client, m2m, deploy_payload, db):
    r = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    assert r.status_code == 201
    body = r.json()
    assert body["target_repository"] == "AlobarQuest/change-manager"
    assert body["pull_request_number"] == 42
    assert body["change_class"] == "dependency-update"
    assert body["acceptance_criteria"] == [
        "/api/health reports the merged commit within 10 minutes"
    ]
    assert body["rollback_plan"]["steps"] == [
        "re-point :main at the previous :<sha>",
        "revert the merge",
    ]
    assert body["status"] == "pending"
    assert body["source"] == "deploy"
    assert body["identity"] == "deploy::AlobarQuest/change-manager::42"

    item = db.get(ChangeItem, body["id"])
    assert item is not None
    # The drift vocabulary is not repurposed, and the free-form blobs stay empty —
    # they are how this schema change would become decorative.
    assert item.plan == {} and item.handoff is None
    assert item.resource_uuid is None and item.resource_name is None
    assert item.instance == "prod" and item.rule_key == "deploying-merge"


def test_the_proposal_is_recorded_in_the_item_history(client, m2m, deploy_payload):
    item_id = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()["id"]
    events = client.get("/api/events", headers=m2m).json()["events"]
    proposed = [e for e in events if e["item_id"] == item_id]
    assert [e["event_type"] for e in proposed] == ["proposed"]
    assert proposed[0]["actor"] == "test"
    assert proposed[0]["to_status"] == "pending"


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"acceptance_criteria": []}, id="no-criteria"),
        pytest.param({"acceptance_criteria": ["  "]}, id="blank-criterion"),
        pytest.param({"rollback_plan": {}}, id="no-rollback-steps"),
        pytest.param({"rollback_plan": {"steps": []}}, id="empty-rollback-steps"),
        pytest.param({"rollback_plan": {"steps": [""]}}, id="blank-rollback-step"),
        pytest.param({"target_repository": ""}, id="blank-repository"),
        pytest.param({"target_repository": "change-manager"}, id="repository-without-owner"),
        pytest.param({"pull_request_number": 0}, id="pull-request-zero"),
        pytest.param({"change_class": " "}, id="blank-change-class"),
        pytest.param({"risk": ""}, id="blank-risk"),
        pytest.param({"reasoning": ""}, id="blank-reasoning"),
        pytest.param({"actor": ""}, id="blank-actor"),
    ],
)
def test_an_incomplete_proposal_is_refused(client, m2m, deploy_payload, db, override):
    r = client.post("/api/deploy-changes", json=deploy_payload(**override), headers=m2m)
    assert r.status_code == 422
    assert db.query(ChangeItem).count() == 0


@pytest.mark.parametrize("field", ["acceptance_criteria", "rollback_plan"])
def test_an_omitted_field_is_refused(client, m2m, deploy_payload, db, field):
    payload = deploy_payload()
    del payload[field]
    assert client.post("/api/deploy-changes", json=payload, headers=m2m).status_code == 422
    assert db.query(ChangeItem).count() == 0


def test_the_ingress_does_not_accept_the_free_form_blobs(client, m2m, deploy_payload, db):
    """`plan` and `handoff` are not inputs, so deploy metadata cannot be smuggled past
    the refusals into a field nothing can check."""
    r = client.post(
        "/api/deploy-changes",
        json=deploy_payload(plan={"rollback": "just wing it"}, handoff={"x": 1}),
        headers=m2m,
    )
    assert r.status_code == 201
    item = db.get(ChangeItem, r.json()["id"])
    assert item is not None
    assert item.plan == {} and item.handoff is None


def test_an_identical_proposal_replays_rather_than_duplicating(client, m2m, deploy_payload, db):
    """A caller that lost our response must be able to retry."""
    first = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    second = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert db.query(ChangeItem).count() == 1


def test_a_different_actor_replaying_the_same_facts_is_not_a_conflict(
    client, m2m, deploy_payload, db
):
    """`actor` says who called, not what the change is."""
    first = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    payload = deploy_payload(actor="someone-else")
    second = client.post("/api/deploy-changes", json=payload, headers=m2m)
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert db.query(ChangeItem).count() == 1


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"acceptance_criteria": ["something else entirely"]}, id="criteria"),
        pytest.param({"rollback_plan": {"steps": ["something else"]}}, id="rollback"),
        pytest.param({"change_class": "software-delivery"}, id="change-class"),
        pytest.param({"risk": "safe"}, id="risk"),
        pytest.param({"reasoning": "a different reason"}, id="reasoning"),
        pytest.param({"note": "added later"}, id="note"),
    ],
)
def test_a_divergent_proposal_for_the_same_pull_request_is_refused(
    client, m2m, deploy_payload, db, override
):
    """Silently returning the stored record would hide the divergence; overwriting it
    would let a second caller rewrite criteria a human may already have approved."""
    client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    r = client.post("/api/deploy-changes", json=deploy_payload(**override), headers=m2m)
    assert r.status_code == 409
    assert next(iter(override)) in r.json()["detail"]
    assert db.query(ChangeItem).count() == 1


def test_a_different_pull_request_gets_its_own_record(client, m2m, deploy_payload, db):
    client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    r = client.post("/api/deploy-changes", json=deploy_payload(pull_request_number=43), headers=m2m)
    assert r.status_code == 201
    assert db.query(ChangeItem).count() == 2


def test_the_ingress_requires_m2m(client, m2m, deploy_payload):
    assert client.post("/api/deploy-changes", json=deploy_payload()).status_code == 401
