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
    # The key case-folds the repository (GitHub names are case-insensitive); the
    # record still stores the name as the proposer wrote it.
    assert body["identity"] == "deploy::alobarquest/change-manager::42"

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


@pytest.mark.parametrize(
    "invisible",
    [
        pytest.param("​", id="zero-width-space"),
        pytest.param("﻿", id="byte-order-mark"),
        pytest.param("­", id="soft-hyphen"),
        pytest.param("‎", id="left-to-right-mark"),
        pytest.param("\xa0", id="non-breaking-space"),
    ],
)
def test_a_criterion_with_nothing_visible_in_it_is_refused(
    client, m2m, deploy_payload, db, invisible
):
    """`str.strip()` removes only `str.isspace()` characters, so these survive it and
    render as an empty bullet. A field that may be a zero-width string is a field that
    will be."""
    for override in (
        {"acceptance_criteria": [invisible]},
        {"rollback_plan": {"steps": [invisible]}},
        {"reasoning": invisible},
    ):
        r = client.post("/api/deploy-changes", json=deploy_payload(**override), headers=m2m)
        assert r.status_code == 422, override
    assert db.query(ChangeItem).count() == 0


def test_the_blank_rule_is_category_based_and_a_blank_looking_LETTER_gets_through(
    client, m2m, deploy_payload
):
    """The residual, recorded rather than hidden.

    The refusal guarantees that a value is not composed *solely* of format, space and
    control characters — which covers what actually happens by accident: a BOM from a
    file read, a zero-width space from a copy-paste. U+3164 HANGUL FILLER renders
    blank but is category `Lo`, a letter, and the set of letters that happen to render
    blank in some font is unbounded. Deliberately submitting one is not an accident,
    and widening the rule to visual blankness is not a boundary that can be held.
    """
    r = client.post(
        "/api/deploy-changes", json=deploy_payload(acceptance_criteria=["ㅤ"]), headers=m2m
    )
    assert r.status_code == 201


@pytest.mark.parametrize(
    "repository",
    [
        pytest.param("../..", id="traversal"),
        pytest.param("a/b?x=1", id="query-string"),
        pytest.param("a/b#frag", id="fragment"),
        pytest.param("a/b/c", id="three-segments"),
        pytest.param("/repo", id="no-owner"),
        pytest.param("owner/", id="no-repo"),
        pytest.param("owner/re po", id="inner-space"),
        pytest.param("https://github.com/a/b", id="url"),
        pytest.param("Alobar​Quest/change-manager", id="zero-width-inside"),
        pytest.param("-owner/repo", id="leading-hyphen"),
        pytest.param("A" * 5000 + "/b", id="absurdly-long"),
    ],
)
def test_a_repository_that_is_not_a_github_name_is_refused(
    client, m2m, deploy_payload, db, repository
):
    """Increments 3 and 4 build GitHub API calls and this record's identity out of
    this string."""
    r = client.post(
        "/api/deploy-changes", json=deploy_payload(target_repository=repository), headers=m2m
    )
    assert r.status_code == 422
    assert db.query(ChangeItem).count() == 0


@pytest.mark.parametrize(
    "number",
    [
        pytest.param(True, id="bool-true-would-coerce-to-pr-1"),
        pytest.param("42", id="numeric-string"),
        pytest.param(2_147_483_648, id="beyond-int4-postgres-only-failure"),
        pytest.param(1.5, id="float"),
    ],
)
def test_a_pull_request_number_that_is_not_one_is_refused(client, m2m, deploy_payload, db, number):
    r = client.post(
        "/api/deploy-changes", json=deploy_payload(pull_request_number=number), headers=m2m
    )
    assert r.status_code == 422
    assert db.query(ChangeItem).count() == 0


def test_the_same_pull_request_in_a_different_case_is_the_same_record(
    client, m2m, deploy_payload, db
):
    """GitHub repository names are case-insensitive, so these are one pull request."""
    first = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    payload = deploy_payload(target_repository="alobarquest/CHANGE-MANAGER")
    second = client.post("/api/deploy-changes", json=payload, headers=m2m)
    assert second.status_code == 409  # same record, and it says a different repository
    assert "target_repository" in second.json()["detail"]
    assert db.query(ChangeItem).count() == 1
    # The stored name is what the first proposer wrote, not the folded key.
    item = db.get(ChangeItem, first.json()["id"])
    assert item is not None and item.target_repository == "AlobarQuest/change-manager"


@pytest.mark.parametrize("field", ["acceptance_criteria", "rollback_plan"])
def test_an_omitted_field_is_refused(client, m2m, deploy_payload, db, field):
    payload = deploy_payload()
    del payload[field]
    assert client.post("/api/deploy-changes", json=payload, headers=m2m).status_code == 422
    assert db.query(ChangeItem).count() == 0


@pytest.mark.parametrize(
    "override",
    [
        pytest.param({"plan": {"rollback": "just wing it"}}, id="plan"),
        pytest.param({"handoff": {"x": 1}}, id="handoff"),
        pytest.param({"source": "drift"}, id="source"),
        pytest.param({"status": "approved"}, id="status"),
        pytest.param({"notes": "a typo for note"}, id="mistyped-note"),
    ],
)
def test_the_ingress_refuses_fields_it_does_not_declare(client, m2m, deploy_payload, db, override):
    """`plan` and `handoff` are not inputs, so deploy metadata cannot be smuggled past
    the refusals into a field nothing can check — and a caller that believes it is
    setting one is told, rather than having it silently dropped."""
    r = client.post("/api/deploy-changes", json=deploy_payload(**override), headers=m2m)
    assert r.status_code == 422
    assert db.query(ChangeItem).count() == 0


def test_a_clean_proposal_leaves_the_free_form_blobs_empty(client, m2m, deploy_payload, db):
    r = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
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
