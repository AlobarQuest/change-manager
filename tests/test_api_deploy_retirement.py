"""POST /api/items/{id}/deploy-retirement — a record whose subject is gone (increment 5b).

The route exists because a record proposed for a pull request that was later CLOSED UNMERGED
stands for a change that can never happen, and nothing retired it. Production item 44 is the live
case, approved by a human before the policy existed.

TWO PROPERTIES CARRY IT, and each gets its own control here rather than an assertion alone.

**The caller supplies a FACT, not a status.** That is why the narrow `propose` credential may
reach it when every other status-moving verb is the full credential's alone; the scope tests state
that half.

**The route is one-directional.** It can only ever REMOVE permission. That is what makes it
acceptable to act on an observation this service has no way to check — the exact thing increment 3
refused to do for policy, where the fact would have GRANTED. A test below states it in outcome
terms rather than trusting the implementation to have only one branch.
"""

from datetime import UTC, datetime

import pytest

from app.deploy_retirement import CLOSED_UNMERGED, RETIRED_EVENT, RETIRED_STATUS
from app.models import ChangeEvent, ChangeItem


@pytest.fixture()
def record(client, m2m, deploy_payload):
    """A deploy record for change-manager#42, as the producer would have proposed it."""
    return client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()


def _retire(client, m2m, item_id, **overrides):
    body = {
        "observation": CLOSED_UNMERGED,
        "pull_request_number": 42,
        "actor": "change-proposer",
        **overrides,
    }
    return client.post(f"/api/items/{item_id}/deploy-retirement", json=body, headers=m2m)


def test_a_record_whose_pull_request_closed_unmerged_is_retired(client, m2m, record, db):
    response = _retire(client, m2m, record["id"])
    assert response.status_code == 200
    assert response.json()["status"] == RETIRED_STATUS

    item = db.get(ChangeItem, record["id"])
    assert item is not None and item.status == RETIRED_STATUS
    assert item.decided_by == "change-proposer" and item.decided_at is not None


def test_the_event_says_why_and_names_the_pull_request(client, m2m, record, db):
    """A machine resolving a decision a human made is only honest if the chain says so."""
    _retire(client, m2m, record["id"])
    events = db.query(ChangeEvent).filter(ChangeEvent.item_id == record["id"]).all()
    retired = [e for e in events if e.event_type == RETIRED_EVENT]
    assert len(retired) == 1
    assert retired[0].to_status == RETIRED_STATUS
    assert retired[0].detail is not None
    assert "#42" in retired[0].detail and "closed without merging" in retired[0].detail


def test_an_approved_record_is_retired_too_because_that_is_the_live_case(client, m2m, record, db):
    """Item 44 is APPROVED. A route that only retired pending records would leave the one
    record this increment exists to retire exactly where it is."""
    item = db.get(ChangeItem, record["id"])
    assert item is not None
    item.status = "approved"
    item.decided_by = "hq-correction"
    db.commit()

    assert _retire(client, m2m, record["id"]).status_code == 200
    db.refresh(item)
    assert item.status == RETIRED_STATUS


def test_a_repeat_retirement_is_a_replay_and_not_a_finding(client, m2m, record, db):
    """The producer sweeps every pass. A retirement it already made must not error."""
    assert _retire(client, m2m, record["id"]).status_code == 200
    second = _retire(client, m2m, record["id"])
    assert second.status_code == 200
    assert second.json()["status"] == RETIRED_STATUS

    events = db.query(ChangeEvent).filter(ChangeEvent.item_id == record["id"]).all()
    assert len([e for e in events if e.event_type == RETIRED_EVENT]) == 1


def test_a_wontfix_record_is_left_exactly_as_a_human_left_it(client, m2m, record, db):
    """`wontfix` is a human's decision and `resolved` is not an upgrade of it. Overwriting it
    would be the machine re-deciding, which is the whole thing this route must not do."""
    item = db.get(ChangeItem, record["id"])
    assert item is not None
    item.status = "wontfix"
    item.decided_by = "devon"
    db.commit()

    assert _retire(client, m2m, record["id"]).status_code == 200
    db.refresh(item)
    assert item.status == "wontfix" and item.decided_by == "devon"


def test_a_different_pull_request_number_is_refused_rather_than_ignored(client, m2m, record, db):
    """Increment 1's kill: a guard keyed on one caller-derived field while the write joined on
    another. The number is what makes the retirement about a subject somebody observed, so a
    caller naming a different one must not have it dropped."""
    response = _retire(client, m2m, record["id"], pull_request_number=99)
    assert response.status_code == 409
    assert "99" in response.json()["detail"]

    item = db.get(ChangeItem, record["id"])
    assert item is not None and item.status != RETIRED_STATUS


def test_an_observation_outside_the_vocabulary_is_refused(client, m2m, record, db):
    response = _retire(client, m2m, record["id"], observation="i_would_rather_it_went_away")
    assert response.status_code == 409

    item = db.get(ChangeItem, record["id"])
    assert item is not None and item.status != RETIRED_STATUS


def test_a_drift_record_cannot_be_retired_by_this_route(client, m2m, db):
    """The general resolve verb stays the full credential's. This one reaches deploy records
    only, which is half of why a narrow credential may hold it.

    It carries the SAME pull request number the retirement names, so the source guard is the only
    one that can refuse it. Without that the subject guard refuses first and this test passes for
    a reason unrelated to its name -- demonstrated, by a mutation deleting the source guard and
    surviving.
    """
    item = ChangeItem(
        identity="prod::some-rule::abc",
        instance="prod",
        rule_key="some-rule",
        source="security",
        status="pending",
        kind="drift",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        reasoning="something drifted",
        risk="caution",
        target_repository="alobarquest/change-manager",
        pull_request_number=42,
        plan={},
    )
    db.add(item)
    db.commit()

    response = client.post(
        f"/api/items/{item.id}/deploy-retirement",
        json={
            "observation": CLOSED_UNMERGED,
            "pull_request_number": 42,
            "actor": "change-proposer",
        },
        headers=m2m,
    )
    assert response.status_code == 409
    db.refresh(item)
    assert item.status == "pending"


def test_the_route_can_reach_exactly_one_status_and_it_removes_permission(client, m2m, db):
    """THE one-directional property, stated in outcome terms.

    Every reachable outcome of this route is a status no landing term accepts. Asserted over the
    statuses actually reached from every starting status a deploy record can hold, rather than by
    reading the implementation -- a second branch added later would show up here as a status this
    set does not contain.
    """
    reached = set()
    for index, start in enumerate(("pending", "approved", "blocked", "resolved", "wontfix")):
        item = ChangeItem(
            identity=f"deploy::alobarquest/change-manager::{100 + index}",
            instance="prod",
            rule_key="deploying-merge",
            source="deploy",
            status=start,
            kind="deploying_merge",
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            reasoning="landing this pull request redeploys production",
            risk="caution",
            plan={},
            target_repository="alobarquest/change-manager",
            pull_request_number=100 + index,
        )
        db.add(item)
        db.commit()
        client.post(
            f"/api/items/{item.id}/deploy-retirement",
            json={
                "observation": CLOSED_UNMERGED,
                "pull_request_number": 100 + index,
                "actor": "change-proposer",
            },
            headers=m2m,
        )
        db.refresh(item)
        reached.add(item.status)

    assert reached == {RETIRED_STATUS, "wontfix"}
    assert "approved" not in reached and "pending" not in reached


def test_an_unknown_item_is_a_404_and_not_a_silent_success(client, m2m):
    assert _retire(client, m2m, 4242).status_code == 404


def test_the_route_rejects_a_body_it_does_not_understand(client, m2m, record):
    """`extra="forbid"`: a caller that believes it is setting a status should learn so."""
    response = client.post(
        f"/api/items/{record['id']}/deploy-retirement",
        json={
            "observation": CLOSED_UNMERGED,
            "pull_request_number": 42,
            "actor": "change-proposer",
            "status": "approved",
        },
        headers=m2m,
    )
    assert response.status_code == 422
