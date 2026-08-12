"""Approval by conformance to a pinned, versioned policy (ADR-0019 increment 5).

The property this module exists to pin is a NEGATIVE one — **no caller can approve a
deploying-merge record** — and negative properties are the ones that ship at half strength,
so each test here carries its discriminating control rather than only its assertion.

The other half is that approval is WRITTEN rather than derived on read. An earlier design
derived it, and three things killed that: `change.approved` is the only event this service
emits that becomes an `authority_grant` in the estate's tamper-evident chain, so a derived
status would have left the single authorization permitting an autonomous production deploy
as the one decision absent from it; the listing filters `status` in SQL against the stored
column, so a derived answer would select the wrong rows in both directions; and a record
must carry the version it was decided under or its approval stops being re-derivable the
moment the policy moves.
"""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.deploy_changes import POLICY_ACTOR, propose_deploy_change
from app.deploy_policy import CURRENT_VERSION, REGISTRY, current, objections, policy_for
from app.models import ChangeEvent, ChangeItem
from app.schemas import DeployChangeIn
from app.transitions import TransitionError, decide


def conformant(**overrides) -> dict:
    """A proposal that matches policy v1 exactly, as the producer would derive it."""
    policy = current()
    repository = "alobarquest/change-manager"
    rollback = policy.rollback_plans[repository]
    return {
        "target_repository": repository,
        "pull_request_number": 49,
        "change_class": "dependency-update",
        "risk": "caution",
        "reasoning": "landing this pull request redeploys production",
        "acceptance_criteria": list(policy.acceptance_criteria[repository]),
        "rollback_plan": rollback.as_stored(),
        "actor": "change-proposer",
        **overrides,
    }


@pytest.fixture()
def file_engine():
    """A real file database, so a second Session is a second CONNECTION."""
    with tempfile.TemporaryDirectory() as d:
        engine = create_engine(f"sqlite:///{Path(d) / 'policy.db'}")
        Base.metadata.create_all(engine)
        yield engine
        engine.dispose()


def _events(db, item_id, event_type):
    return db.scalars(
        select(ChangeEvent).where(
            ChangeEvent.item_id == item_id, ChangeEvent.event_type == event_type
        )
    ).all()


# ---------------------------------------------------------------------------
# The server approves; nothing else does.
# ---------------------------------------------------------------------------


def test_a_conformant_proposal_is_approved_by_the_server(client, m2m, db):
    body = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()
    assert body["status"] == "approved"
    assert body["policy_version"] == CURRENT_VERSION
    assert body["policy_objections"] == []

    item = db.get(ChangeItem, body["id"])
    assert item.decided_by == "deploy-policy"
    assert item.decided_at is not None


def test_the_approval_enters_the_events_feed_as_an_approval(client, m2m, db):
    """The feed is what becomes an `authority_grant` in the tamper-evident chain.

    `_GRANT_TYPES` in the factory-events adapter is exactly `{"approved"}`, and the grant's
    approver is the event's actor. An approval that emitted no event, or emitted one under
    another name, would be the only authorization permitting an autonomous production
    deploy that never entered the chain.
    """
    item_id = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()["id"]
    feed = client.get("/api/events", headers=m2m).json()["events"]
    mine = [e for e in feed if e["item_id"] == item_id]
    assert [e["event_type"] for e in mine] == ["proposed", "approved"]
    approved = mine[-1]
    assert approved["actor"] == "deploy-policy"
    assert approved["from_status"] == "pending" and approved["to_status"] == "approved"
    assert f"v{CURRENT_VERSION}" in approved["detail"]


def test_a_non_conformant_proposal_stays_pending_and_says_why(client, m2m, deploy_payload):
    """The stock payload's criteria are not the ones a human pinned, so it is not approved."""
    body = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()
    assert body["status"] == "pending"
    assert body["policy_version"] is None
    assert "acceptance_criteria_not_ratified" in body["policy_objections"]


def test_a_repository_outside_the_policy_is_not_approved(client, m2m, db):
    body = client.post(
        "/api/deploy-changes",
        json=conformant(target_repository="alobarquest/brain"),
        headers=m2m,
    ).json()
    assert body["status"] == "pending"
    assert body["policy_objections"] == ["repository_not_in_policy"]


@pytest.mark.parametrize(
    "override,objection",
    [
        pytest.param(
            {"change_class": "software-delivery"}, "change_class_not_in_policy", id="class"
        ),
        pytest.param({"risk": "safe"}, "risk_not_in_policy", id="risk"),
        pytest.param(
            {"acceptance_criteria": ["something a human never ratified"]},
            "acceptance_criteria_not_ratified",
            id="criteria",
        ),
        pytest.param(
            {"rollback_plan": {"steps": ["improvise"], "target": "commit"}},
            "rollback_plan_not_ratified",
            id="rollback",
        ),
    ],
)
def test_each_policy_term_can_refuse_on_its_own(client, m2m, override, objection):
    """Every term fires, so none of them is decoration.

    Written parametrized rather than as one payload breaking everything at once: a single
    combined case passes even when three of the four terms are never evaluated.
    """
    body = client.post("/api/deploy-changes", json=conformant(**override), headers=m2m).json()
    assert body["status"] == "pending"
    assert objection in body["policy_objections"]


# ---------------------------------------------------------------------------
# No caller can approve. Each with its control.
# ---------------------------------------------------------------------------


def test_the_full_bearer_cannot_approve_a_deploy_record(client, m2m, db, deploy_payload):
    """`m2m` is the FULL bearer — the widest credential this service has.

    Increment 4 made the *producer* unable to approve. This is wider: nothing can, however
    privileged. The control on the next lines is what makes the refusal mean something —
    the same bearer, the same route, a derived item, and it works.
    """
    item_id = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()["id"]
    refused = client.post(f"/api/items/{item_id}/approve", json={"actor": "devon"}, headers=m2m)
    assert refused.status_code == 409
    assert "approved by policy conformance" in refused.json()["detail"]
    db.expire_all()
    assert db.get(ChangeItem, item_id).status == "pending"

    drift = ChangeItem(
        identity="prod::some-rule::abc",
        instance="prod",
        rule_key="some-rule",
        risk="caution",
        kind="config",
        reasoning="a derived change",
        plan={},
        status="pending",
        source="drift",
        first_seen_at=db.get(ChangeItem, item_id).first_seen_at,
        last_seen_at=db.get(ChangeItem, item_id).last_seen_at,
    )
    db.add(drift)
    db.commit()
    allowed = client.post(f"/api/items/{drift.id}/approve", json={"actor": "devon"}, headers=m2m)
    assert allowed.status_code == 200, "the control failed: this refusal proves nothing"
    assert allowed.json()["status"] == "approved"


def test_the_write_path_refuses_even_when_no_route_checked(db, deploy_payload):
    """The guarantee is on the write, not on the door.

    `decide` has six callers — five API verbs and the GUI — and increment 1's kill in this
    repository was a guard keyed on the right concept at the wrong place. A future seventh
    caller inherits this; it would not inherit a check in a route body.
    """
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    with pytest.raises(TransitionError, match="not by a caller"):
        decide(db, item, actor="devon", new_status="approved", event_type="approved")
    db.expire_all()
    assert db.get(ChangeItem, item.id).status == "pending"


def test_the_write_path_still_permits_every_veto(db, deploy_payload):
    """Policy grants; a human revokes. Only the grant is closed.

    Without this, "no caller can approve" could have been implemented as "no caller can
    decide", which would strand every record nothing will ever claim.
    """
    for verb, status in (
        ("deferred", "deferred"),
        ("wontfixed", "wontfix"),
        ("resolved", "resolved"),
    ):
        item, _ = propose_deploy_change(
            db, DeployChangeIn(**deploy_payload(pull_request_number=hash(verb) % 9000 + 100))
        )
        decide(db, item, actor="devon", new_status=status, event_type=verb)
        db.expire_all()
        assert db.get(ChangeItem, item.id).status == status


# ---------------------------------------------------------------------------
# The policy moves. So does the world.
# ---------------------------------------------------------------------------


def test_refreshed_criteria_revoke_an_approval(client, m2m, db):
    """The concern the old conflict test carried, answered by revocation.

    Refusing a changed derivation was a permanent brick; accepting it silently would let a
    second caller rewrite the criteria an approval rested on. Revoking is the third answer:
    the facts move, the approval does not survive them, and the record says so.
    """
    first = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()
    assert first["status"] == "approved"

    moved = client.post(
        "/api/deploy-changes",
        json=conformant(acceptance_criteria=["the rollout now proves something else"]),
        headers=m2m,
    ).json()
    assert moved["status"] == "pending"
    assert moved["policy_version"] is None
    assert "acceptance_criteria_not_ratified" in moved["policy_objections"]
    assert len(_events(db, first["id"], "policy_revoked")) == 1
    assert len(_events(db, first["id"], "criteria_refreshed")) == 1


def test_a_record_that_becomes_conformant_is_approved_on_the_next_pass(client, m2m, db):
    """The producer runs hourly; that cadence is what makes a policy bump take effect.

    Here the record is created non-conformant and a later proposal brings its derived facts
    into line — the same path a bumped policy travels, from the other direction.
    """
    stale = client.post(
        "/api/deploy-changes",
        json=conformant(acceptance_criteria=["what the rollout used to prove"]),
        headers=m2m,
    ).json()
    assert stale["status"] == "pending"

    now = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()
    assert now["id"] == stale["id"]
    assert now["status"] == "approved"
    assert now["policy_version"] == CURRENT_VERSION
    assert len(_events(db, stale["id"], "approved")) == 1


def test_policy_never_overrides_a_human_veto(client, m2m, db, deploy_payload):
    """`_POLICY_MAY_MOVE` enumerates what policy MAY change, which is the fail-closed
    polarity: a status nobody thought about is left alone, where a denylist would admit it.
    """
    item, _ = propose_deploy_change(db, DeployChangeIn(**conformant()))
    assert item.status == "approved"
    decide(db, item, actor="devon", new_status="wontfix", event_type="wontfixed")

    replay = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()
    assert replay["status"] == "wontfix", "policy re-approved a record a human had vetoed"
    assert replay["policy_version"] == CURRENT_VERSION, "the version it WAS approved under is kept"


def test_the_approval_survives_a_separate_connection(file_engine):
    """A persistence assertion must re-read through a reader that cannot see an
    uncommitted write.

    A FILE database, not the suite's `:memory:` one. `expire_all()` re-SELECTs inside the
    same open transaction, where a flushed-but-uncommitted row is perfectly visible — and
    the shared-cache `StaticPool` the other fixtures use hands both sessions the SAME
    connection, so a "second session" there is the same trap wearing a disguise. This is
    the only reader in the suite that would actually notice a missing commit.
    """
    with Session(file_engine) as writing:
        item, created = propose_deploy_change(writing, DeployChangeIn(**conformant()))
        assert created and item.status == "approved"
        item_id = item.id

    with Session(file_engine) as other:
        stored = other.get(ChangeItem, item_id)
        assert stored is not None
        assert stored.status == "approved"
        assert stored.policy_version == CURRENT_VERSION
        assert stored.decided_by == POLICY_ACTOR


# ---------------------------------------------------------------------------
# The artifact itself.
# ---------------------------------------------------------------------------


def test_every_version_is_retained_and_keyed_by_its_own_number():
    """A superseded version is never edited and never dropped: a record stores the number
    it was decided under, and re-evaluating that approval means finding what it said."""
    assert REGISTRY, "an empty registry approves nothing and would look like a passing gate"
    for number, policy in REGISTRY.items():
        assert policy.version == number
    assert CURRENT_VERSION in REGISTRY


def test_an_unknown_version_is_a_finding_rather_than_a_default():
    assert policy_for(CURRENT_VERSION) is current()
    assert policy_for(max(REGISTRY) + 1) is None


def test_the_policy_pins_a_criteria_and_rollback_entry_for_every_repository_it_names():
    """A repository in the allowlist with nothing pinned would be approved on repository
    alone, which is the one term that says nothing about what the deploy is held to."""
    policy = current()
    for repository in policy.repositories:
        assert repository in policy.acceptance_criteria
        assert repository in policy.rollback_plans
        assert policy.acceptance_criteria[repository], "an empty criteria tuple ratifies nothing"


@pytest.mark.parametrize("field", ["target_repository", "change_class", "risk"])
def test_an_unreadable_field_is_an_objection_rather_than_a_skip(field):
    """Fail closed on shape. The only way through this function is to be exactly what a
    human pinned, so a `None` must never read as "nothing to compare"."""

    class Row:
        pass

    row = Row()
    for name, value in conformant().items():
        setattr(row, name, value)
    setattr(row, field, None)
    assert objections(current(), row)


def test_the_landing_conditions_are_declared_but_not_evaluated_here():
    """This service has no GitHub egress, so these are served for the party that has."""
    policy = current()
    assert policy.landing.update_types == frozenset({"semver-patch", "semver-minor"})
    assert policy.landing.require_head_current_with_base is True


def test_the_policy_route_serves_the_conditions_a_landing_needs(client, m2m):
    body = client.get("/api/deploy-policy", headers=m2m).json()
    assert body["version"] == CURRENT_VERSION
    assert body["repositories"] == ["alobarquest/change-manager"]
    assert body["landing"]["update_types"] == ["semver-minor", "semver-patch"]
    assert body["landing"]["require_head_current_with_base"] is True


def test_the_policy_route_requires_a_credential(client):
    assert client.get("/api/deploy-policy").status_code == 401


# ---------------------------------------------------------------------------
# Version 2 -- the rollout-workflow pin (ADR-0019 increment 5b).
# ---------------------------------------------------------------------------


def test_version_one_is_retained_verbatim_and_declares_no_pin():
    """The editing contract, stated as a test rather than only as prose.

    Version 1 predates `rollout_workflows`, so it must still be readable exactly as it was
    decided. The default is empty rather than absent so the dataclass can gain the field, and
    an empty pin is NOT a waived condition -- the landing party fails closed on a repository it
    has no pin for. Asserting emptiness here is what makes that reading load-bearing: if some
    later edit quietly gave version 1 a pin, a record approved under it would start meaning
    something nobody decided in 2026-08-11.
    """
    v1 = policy_for(1)
    assert v1 is not None
    assert v1.landing.rollout_workflows == {}
    assert v1.decided == "2026-08-11"


def test_the_current_version_pins_the_rollout_workflow_of_every_repository_it_names():
    """A repository the policy admits with no pinned workflow is a repository whose criteria
    describe bytes nobody named, which is the hole this version exists to close."""
    policy = current()
    assert CURRENT_VERSION == 2
    for repository in policy.repositories:
        pin = policy.landing.rollout_workflows.get(repository)
        assert pin is not None, f"{repository} is admitted with no rollout-workflow pin"
        assert pin.path and pin.blob_sha
        assert len(pin.blob_sha) == 40 and pin.blob_sha == pin.blob_sha.lower()


def test_the_pin_names_the_revision_the_criteria_were_written_about():
    """The pin and the criteria are two halves of one judgment, and nothing else joins them.

    `a47d4b18…` is the `191ec5a` revision of change-manager's rollout, the one that polls
    /api/health until it reports the merged commit. The acceptance criteria say exactly that. A
    pin naming some other blob would leave the policy asserting a guarantee about bytes that do
    not make it.
    """
    policy = current()
    repository = "alobarquest/change-manager"
    pin = policy.landing.rollout_workflows[repository]
    assert pin.path == ".github/workflows/deploy.yml"
    assert pin.blob_sha == "a47d4b187c93971a5b5915ce87a963bd4ef35e30"
    assert any("api/health" in c for c in policy.acceptance_criteria[repository])


def test_the_route_serves_the_pin_so_the_landing_party_holds_no_copy(client, m2m):
    """The whole reason the condition is declared here and evaluated there."""
    landing = client.get("/api/deploy-policy", headers=m2m).json()["landing"]
    assert landing["rollout_workflows"] == {
        "alobarquest/change-manager": {
            "path": ".github/workflows/deploy.yml",
            "blob_sha": "a47d4b187c93971a5b5915ce87a963bd4ef35e30",
        }
    }


def test_version_two_narrows_and_does_not_widen():
    """Every shape version 1 admitted, version 2 admits; the only change is a new condition
    on the act. Stated as a test because "additive" is the claim that makes it safe to bump
    while records approved under version 1 are still waiting."""
    v1, v2 = policy_for(1), policy_for(2)
    assert v1 is not None and v2 is not None
    assert v2.repositories == v1.repositories
    assert v2.change_classes == v1.change_classes
    assert v2.risks == v1.risks
    assert v2.acceptance_criteria == v1.acceptance_criteria
    assert v2.rollback_plans == v1.rollback_plans
    assert v2.landing.update_types == v1.landing.update_types
    assert v2.landing.require_head_current_with_base is True
