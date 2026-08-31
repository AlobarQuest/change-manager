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
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.deploy_changes import POLICY_ACTOR, propose_deploy_change
from app.deploy_policy import (
    CURRENT_VERSION,
    DEPENDABOT,
    DOCKER,
    GITHUB_ACTIONS,
    REGISTRY,
    current,
    inert_landing_dict,
    landing_conditions_dict,
    objections,
    policy_dict,
    policy_for,
)
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
    """The subject was `alobarquest/brain` until version 3 admitted it. Any repository whose
    landing this estate has not pinned a rollout and a remedy for will do; the orchestrator's own
    repository is one where landing is inert, so it will never be a subject of this policy."""
    body = client.post(
        "/api/deploy-changes",
        json=conformant(target_repository="alobarquest/orchestrator"),
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
    """This service has no GitHub egress, so these are served for the party that has.

    Since version 5 the ecosystem is one of them, and it is the clearest case of the rule this
    docstring states: the ecosystem is the second segment of the branch the update bot opened,
    which lives in GitHub, so this file names the excluded set and the landing party reads which
    one a pull request is in.
    """
    policy = current()
    assert policy.landing.excluded_ecosystems == frozenset({"github_actions"})
    assert policy.landing.update_types == frozenset()
    assert policy.landing.require_head_current_with_base is True


def test_the_policy_route_serves_the_conditions_a_landing_needs(client, m2m):
    body = client.get("/api/deploy-policy", headers=m2m).json()
    assert body["version"] == CURRENT_VERSION
    assert body["repositories"] == ["alobarquest/brain", "alobarquest/change-manager"]
    assert body["landing"]["excluded_ecosystems"] == ["github_actions"]
    assert body["landing"]["update_types"] == []
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
    assert CURRENT_VERSION == 6
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
        "alobarquest/brain": {
            "path": ".github/workflows/ci.yml",
            "blob_sha": "c5c088719cd340f0071b875c6a82439292ed8756",
        },
        "alobarquest/change-manager": {
            "path": ".github/workflows/deploy.yml",
            "blob_sha": "a47d4b187c93971a5b5915ce87a963bd4ef35e30",
        },
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


def test_the_record_row_carries_the_conditions_the_landing_party_must_evaluate(client, m2m, db):
    """ADR-0019 increment 5b. The landing party reads the conditions where it reads the record.

    `GET /api/deploy-policy` still serves them standing alone. This projection exists because the
    orchestrator's architecture guards forbid the bare token that route's path is spelled with --
    measured, not predicted -- and because reading both from one response means the version a
    record was approved under and the version now in force cannot disagree across two calls.
    """
    item = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()
    assert item["policy_version"] == CURRENT_VERSION
    assert item["landing_policy_version"] == CURRENT_VERSION
    assert (
        item["landing_conditions"]
        == client.get("/api/deploy-policy", headers=m2m).json()["landing"]
    )


def test_the_two_version_fields_are_not_the_same_question(client, m2m, db):
    """`policy_version` is what approved THIS record; `landing_policy_version` is what is in
    force now. They are equal today and the landing refuses when they are not, which is the only
    mechanism by which moving the policy binds an approval that already exists."""
    item = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()
    row = db.get(ChangeItem, item["id"])
    assert row is not None
    row.policy_version = 1
    db.commit()

    served = client.get("/api/items?source=deploy", headers=m2m).json()[0]
    assert served["policy_version"] == 1
    assert served["landing_policy_version"] == CURRENT_VERSION == 6


def test_a_drift_record_carries_no_landing_conditions(client, m2m, db):
    """They are conditions on a deploying merge. A drift item is not one, and serving them
    against it would invite a consumer to read policy that says nothing about it."""
    item = ChangeItem(
        identity="prod::some-rule::abc",
        instance="prod",
        rule_key="some-rule",
        kind="drift",
        reasoning="something drifted",
        risk="caution",
        source="security",
        status="pending",
        plan={},
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
    )
    db.add(item)
    db.commit()
    served = client.get("/api/items?source=security", headers=m2m).json()
    assert served and served[0]["landing_conditions"] is None


def test_a_record_that_still_conforms_is_re_approved_under_the_NEWER_version(client, m2m, db):
    """THE branch without which a version bump is permanent brickage.

    A record approved under version 1 that still conforms under version 2 matches neither the
    approve branch (which needs a status that is not already approved) nor the revoke branch
    (which needs an objection). There is no other route: `approve` is refused to every caller
    including the full bearer, and the identity is held so no fresh record can be proposed. The
    landing binds an approval to the version IN FORCE, so a stranded record is unlandable forever.
    """
    item_id = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()["id"]
    row = db.get(ChangeItem, item_id)
    assert row is not None
    row.policy_version = 1
    db.commit()

    replay = client.post("/api/deploy-changes", json=conformant(), headers=m2m)

    assert replay.status_code == 200
    assert replay.json()["policy_version"] == CURRENT_VERSION
    db.refresh(row)
    assert row.status == "approved" and row.decided_by == POLICY_ACTOR


def test_the_re_approval_enters_the_chain_as_a_grant_of_its_own(client, m2m, db):
    """A version bump is a fresh human decision about what may land unattended, and `approved` is
    the only thing this service emits that becomes an authority grant. Re-stamping the column
    silently would leave the grant under the newer version absent from the chain while the one it
    replaced is in it."""
    item_id = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()["id"]
    row = db.get(ChangeItem, item_id)
    assert row is not None
    row.policy_version = 1
    db.commit()
    before = len(_events(db, item_id, "approved"))

    client.post("/api/deploy-changes", json=conformant(), headers=m2m)

    approvals = _events(db, item_id, "approved")
    assert len(approvals) == before + 1
    assert f"v{CURRENT_VERSION}" in (approvals[-1].detail or "")


def test_a_record_already_on_the_current_version_is_not_re_stamped(client, m2m, db):
    """The control. Without it the branch above would pass for one that emits a grant on every
    pass -- an authority-grant row per hour, for a decision nobody made."""
    item_id = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()["id"]
    before = len(_events(db, item_id, "approved"))

    client.post("/api/deploy-changes", json=conformant(), headers=m2m)

    assert len(_events(db, item_id, "approved")) == before


def test_a_record_that_stops_conforming_is_still_revoked_rather_than_re_stamped(
    client, m2m, db, deploy_payload
):
    """The other control: the new branch must not swallow the revocation. An approved record on an
    old version whose shape no longer conforms goes back to pending, not forward to the new
    version."""
    item_id = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()["id"]
    row = db.get(ChangeItem, item_id)
    assert row is not None
    row.policy_version = 1
    row.risk = "reckless"
    db.commit()

    client.post("/api/deploy-changes", json=conformant(risk="reckless"), headers=m2m)

    db.refresh(row)
    assert row.status == "pending" and row.policy_version is None


def test_a_record_a_HUMAN_approved_is_never_restamped_as_policy_approved(client, m2m, db):
    """`None != 2` is true, so the re-approval branch needs an explicit not-None clause.

    Without it, the one record shape the landing party refuses -- approved by a person before any
    policy existed, which is production item 44 -- would be converted into a policy approval here,
    its approver overwritten, and an `approved` event claiming conformance would enter the
    tamper-evident chain. The landing party cannot see the difference; this is where it is kept.
    """
    item_id = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()["id"]
    row = db.get(ChangeItem, item_id)
    assert row is not None
    row.policy_version = None
    row.decided_by = "hq-correction"
    db.commit()
    before = len(_events(db, item_id, "approved"))

    client.post("/api/deploy-changes", json=conformant(), headers=m2m)

    db.refresh(row)
    assert row.policy_version is None, "a human's approval was restamped as a policy approval"
    assert row.decided_by == "hq-correction", "a human's name was overwritten"
    assert len(_events(db, item_id, "approved")) == before


# ---------------------------------------------------------------------------
# Version 3 -- brain joins (ADR-0019).
# ---------------------------------------------------------------------------

BRAIN = "alobarquest/brain"
CHANGE_MANAGER = "alobarquest/change-manager"

# The pre-#47 revision of brain's ci.yml. A green run at THESE bytes proved only that a domain
# answered 2xx thirty seconds after the webhook, which version 1 named as the reason brain could
# not join. Kept as a literal so the pin below is asserted against the thing it must not be.
_BRAIN_ROLLOUT_BEFORE_THE_REVISION_POLL = "6cad4cf9f03d816ce8bf8fb87fa67d8634486ef1"


def brain_conformant(**overrides) -> dict:
    """A brain proposal as the producer derives one, built from the policy it must match."""
    policy = current()
    return {
        "target_repository": BRAIN,
        "pull_request_number": 33,
        "change_class": "dependency-update",
        "risk": "caution",
        "reasoning": "landing this pull request redeploys production",
        "acceptance_criteria": list(policy.acceptance_criteria[BRAIN]),
        "rollback_plan": policy.rollback_plans[BRAIN].as_stored(),
        "actor": "change-proposer",
        **overrides,
    }


def test_version_three_admits_brain_and_leaves_change_manager_exactly_as_it_was():
    """Both halves, because either alone is the wrong change.

    A version that admits brain by loosening something change-manager relied on is a regression
    with three consecutive autonomous landings behind it; a version that changes change-manager's
    terms would silently re-decide what those landings were approved under.
    """
    v2, v3 = policy_for(2), policy_for(3)
    assert v2 is not None and v3 is not None

    assert v3.repositories == v2.repositories | {BRAIN}
    assert v3.change_classes == v2.change_classes
    assert v3.risks == v2.risks
    assert v3.landing.update_types == v2.landing.update_types
    assert v3.landing.require_head_current_with_base is True

    cm = CHANGE_MANAGER
    assert v3.acceptance_criteria[cm] == v2.acceptance_criteria[cm]
    assert v3.rollback_plans[cm] == v2.rollback_plans[cm]
    assert v3.landing.rollout_workflows[cm] == v2.landing.rollout_workflows[cm]


def test_brains_criteria_are_its_own_and_not_change_managers():
    """Four applications is the whole difference, so a shared tuple would be a record that lies
    about what its rollout checked."""
    policy = current()
    assert policy.acceptance_criteria[BRAIN] != policy.acceptance_criteria[CHANGE_MANAGER]
    assert policy.rollback_plans[BRAIN] != policy.rollback_plans[CHANGE_MANAGER]


def test_brains_criteria_transcribe_the_revision_poll_and_not_the_liveness_poll():
    """The discriminating assertion on the judgment this version makes.

    Every earlier revision of brain's rollout attested that a domain ANSWERED, and the producer
    appends an explicit "does NOT prove the merged build is the one serving production" line to
    criteria derived from one. Transcribing an older attestation here would therefore be visible
    as that line -- and would admit, under a policy whose whole premise is that brain now verifies
    the revision, criteria saying it does not.

    The second half is the ceiling this version accepted deliberately: what is attested is every
    application the rollout TRIGGERED, never "all four", because the bytes skip an application
    whose Coolify secret is unset and no pin over bytes can read a secret.
    """
    criteria = current().acceptance_criteria[BRAIN]
    assert not any("does NOT prove" in c for c in criteria)
    assert any("every brain application this rollout triggered" in c for c in criteria)
    assert not any("all four" in c for c in criteria)


def test_brains_criteria_are_the_pair_the_producer_derives_for_this_workflow_revision():
    """THE CROSS-REPO PAIR, spelled out, because nothing mechanical joins the two sides.

    `objections` byte-compares a record's stored criteria against this tuple, and a record's
    stored criteria are what the orchestrator's `change_proposer.criteria.acceptance_criteria`
    derived from its transcription of the blob pinned below. The same literal is asserted there,
    in `tests/change_proposer/test_change_proposer.py`. They drift, and every brain record objects
    `acceptance_criteria_not_ratified` forever with nothing anywhere saying which side moved.

    A literal rather than a property assertion for exactly that reason: a substring check leaves
    most of the string free to move silently, and a mutation of the wording proved it does. This
    cannot be edited on one side without editing a pinned test on that side, which is the signal.

    Two criteria and no third: the producer appends its "does NOT prove" line only below the
    revision-confirming attestation level, and this revision is at it.
    """
    assert current().acceptance_criteria[BRAIN] == (
        "the rollout runs for this merge on alobarquest/brain, and its production step "
        "concludes success (job 'deploy', step 'Deploy brain apps')",
        "every brain application this rollout triggered answered /api/health reporting the "
        "merged commit as its revision and a status of ok, within 600 seconds; an application "
        "whose Coolify UUID secret is unset is neither triggered nor checked, and a rollout "
        "that triggered none fails rather than passing empty",
    )


def test_brains_rollback_plan_is_the_one_the_producer_transcribes():
    """The same cross-repo pair, one field over, and it fails the same silent way: `rollback_plan`
    is compared byte-for-byte too, so a remedy improved on one side alone stops every brain record
    conforming. The orchestrator's copy is `change_proposer.criteria._ROLLBACKS`."""
    assert current().rollback_plans[BRAIN].as_stored() == {
        "steps": [
            "re-point each affected app's moving image tag at the previous per-SHA tag "
            "and redeploy",
            "revert the merge commit on main, so main and production agree again",
        ],
        "target": "image",
    }


def test_brains_pin_names_the_workflow_that_verifies_the_revision():
    """`ci.yml`, not `deploy.yml` -- brain has no deploy.yml, its deploy job lives in the CI
    workflow -- and the blob is the revision that replaced the liveness poll. A pin left on the
    superseded revision would admit exactly the criteria the test above refuses.
    """
    pin = current().landing.rollout_workflows[BRAIN]
    assert pin.path == ".github/workflows/ci.yml"
    assert pin.blob_sha == "c5c088719cd340f0071b875c6a82439292ed8756"
    assert pin.blob_sha != _BRAIN_ROLLOUT_BEFORE_THE_REVISION_POLL
    assert pin != current().landing.rollout_workflows[CHANGE_MANAGER]


def test_a_brain_proposal_conforms_and_is_approved_by_the_server(client, m2m, db):
    """The affirmative case. A version that admits a repository nothing can conform to is a
    version that reads as shipped and lands nothing."""
    response = client.post("/api/deploy-changes", json=brain_conformant(), headers=m2m)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "approved"
    assert body["policy_version"] == CURRENT_VERSION
    row = db.get(ChangeItem, body["id"])
    assert row is not None and row.decided_by == POLICY_ACTOR


def test_a_brain_record_carrying_change_managers_criteria_is_refused(client, m2m):
    """The control on the affirmative case above: approval is by conformance to what a human
    pinned FOR THIS REPOSITORY, so the criteria are not interchangeable between the two."""
    borrowed = brain_conformant(
        acceptance_criteria=list(current().acceptance_criteria[CHANGE_MANAGER])
    )

    body = client.post("/api/deploy-changes", json=borrowed, headers=m2m).json()

    assert body["status"] == "pending"
    assert body["policy_version"] is None


def test_a_record_approved_under_version_two_is_bound_until_it_is_re_approved(client, m2m, db):
    """The bump BINDS, which is what makes a narrowing take effect on approvals that already
    exist. Production item 50 is the live subject: approved under version 2 when this shipped.

    This service never re-decides on a read, so the record keeps the version that approved it and
    the two version fields disagree -- which is what the landing party refuses on. Both directions
    are asserted: the disagreement, and the repeat proposal that clears it.
    """
    item_id = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()["id"]
    row = db.get(ChangeItem, item_id)
    assert row is not None
    row.policy_version = 2
    db.commit()

    served = client.get("/api/items?source=deploy", headers=m2m).json()[0]
    assert served["policy_version"] == 2
    assert served["landing_policy_version"] == 6

    replay = client.post("/api/deploy-changes", json=conformant(), headers=m2m)

    assert replay.json()["policy_version"] == 6


def test_version_three_did_not_widen_what_may_land():
    """brain's queue held two requirement-range bumps, and version 3 left them unlandable.

    A requirement range states no single delta, so it carried no update type at all and was
    refused for want of a parseable delta -- by the party that reads GitHub, since this service
    cannot. What is asserted is that version 3 gave brain no allowance of its own: one update-type
    set governed both repositories, and it was still patch and minor.

    **READ FROM `policy_for(3)` AND NO LONGER FROM THE ROUTE**, which is the correction version 5
    forces rather than a tidy-up. Written against the route, this test asserted a property of
    whatever version happens to be current, under a name that says version 3 -- so version 5
    changing what may land would have reddened a test about a version it does not touch, and a
    reader would have had to decide which of the two things the test meant. Version 3 is retained
    verbatim, so its own terms are what a test about version 3 must read.
    """
    v3 = policy_for(3)
    assert v3 is not None
    assert v3.landing.update_types == frozenset({"semver-minor", "semver-patch"})
    assert v3.landing.excluded_ecosystems is None, "version 3 predates the outcome rule"
    assert set(v3.landing.rollout_workflows) == {BRAIN, CHANGE_MANAGER}


# ---------------------------------------------------------------------------
# Version 4 -- the factory class joins (ADR-0025).
# ---------------------------------------------------------------------------

FACTORY_CLASS = "factory-delivery"
BOT_CLASS = "dependency-update"

# A class the orchestrator really does use for other work and that NO version of this policy has
# ever admitted. It is the discriminating control on every affirmative test below: a version that
# admitted the factory class by loosening the class term itself would pass all of them and refuse
# nothing, and this is the assertion that tells the two apart.
_A_CLASS_NO_VERSION_ADMITS = "software-delivery"


def factory_conformant(**overrides) -> dict:
    """A factory record as `change_proposer` derives one: change-manager's terms, its own class.

    `change_class` is the field POLICY reads: the producer writes `BOT_CHANGE_CLASS` when a pull
    request has no work-unit id in its title and `FACTORY_CHANGE_CLASS` when it has one, and this
    fixture varies exactly that.

    It is NOT the only field that differs, and saying so would be wrong: `_reasoning` also appends
    a sentence naming the work unit. That field is not a policy term, so conformance is unaffected
    -- but a real factory payload and a bot's are not interchangeable, and a fixture claiming they
    were would invite a later reader to test one believing it had tested both.
    """
    defaults = {"change_class": FACTORY_CLASS, "pull_request_number": 81}
    return conformant(**{**defaults, **overrides})


def test_version_four_admits_the_factory_class_and_changes_nothing_else():
    """Both halves, because either alone is the wrong change.

    A version that admits the factory class by also moving a repository, a criterion, a remedy or
    a condition on the act would re-decide, silently, terms that three consecutive autonomous
    landings were approved under. And a version that changed nothing would be a version that
    reads as shipped and approves no factory record.

    Asserted as an EXACT union rather than as membership: `>= v3.change_classes | {factory}` is
    satisfied by a version that admits everything, which is the failure this grant is narrow to
    avoid.
    """
    v3, v4 = policy_for(3), policy_for(4)
    assert v3 is not None and v4 is not None

    assert v4.change_classes == v3.change_classes | {FACTORY_CLASS}
    assert BOT_CLASS in v4.change_classes, "the class it already admitted is still admitted"
    assert _A_CLASS_NO_VERSION_ADMITS not in v4.change_classes

    assert v4.repositories == v3.repositories
    assert v4.risks == v3.risks
    assert v4.acceptance_criteria == v3.acceptance_criteria
    assert v4.rollback_plans == v3.rollback_plans
    assert v4.landing.update_types == v3.landing.update_types
    assert v4.landing.require_head_current_with_base is True
    assert v4.landing.rollout_workflows == v3.landing.rollout_workflows


def test_version_fours_rationale_records_the_decision_it_rests_on():
    """The `rationale` string is the RECORD, which is what every version of this file uses it as.

    Pinned as a citation and a subject rather than as prose, because prose is exactly what a
    version bump should be free to word for itself. What it must not be free to do is ship
    version 3's rationale copied over -- a version whose recorded reasoning describes a grant it
    does not make, and the only artifact a reader re-deriving this approval in a year will have.
    """
    v3, v4 = policy_for(3), policy_for(4)
    assert v3 is not None and v4 is not None
    assert "ADR-0025" in v4.rationale
    assert FACTORY_CLASS in v4.rationale
    assert v4.rationale != v3.rationale


def test_a_factory_proposal_conforms_and_is_approved_by_the_server(client, m2m, db):
    """ADR-0025's whole subject: no per-record human approval, so conformance decides.

    Before version 4 this exact payload was refused `change_class_not_in_policy` and sat pending
    until a person clicked -- and change-manager has no GitHub egress, so what that person would
    have been shown could not have included the change.
    """
    response = client.post("/api/deploy-changes", json=factory_conformant(), headers=m2m)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "approved"
    assert body["policy_objections"] == []
    assert body["policy_version"] == CURRENT_VERSION
    row = db.get(ChangeItem, body["id"])
    assert row is not None and row.decided_by == POLICY_ACTOR


def test_a_factory_proposal_for_brain_is_approved_on_the_same_terms(client, m2m, db):
    """The grant is over the CLASS, so it reaches every repository the policy already named --
    and it reaches them on each repository's own criteria, which brain's differ in."""
    payload = brain_conformant(change_class=FACTORY_CLASS, pull_request_number=82)

    body = client.post("/api/deploy-changes", json=payload, headers=m2m).json()

    assert body["status"] == "approved"
    assert body["policy_version"] == CURRENT_VERSION


def test_a_factory_record_for_a_repository_outside_the_policy_is_still_refused(client, m2m):
    """THE CLASS GRANT DID NOT BECOME A REPOSITORY GRANT, which is ADR-0025's first boundary.

    Sent carrying change-manager's ratified criteria and remedy, so the repository term is the
    only thing left that can refuse it -- a payload that also failed on criteria would pass this
    test with the repository term deleted.
    """
    borrowed = factory_conformant(target_repository="alobarquest/orchestrator")

    body = client.post("/api/deploy-changes", json=borrowed, headers=m2m).json()

    assert body["status"] == "pending"
    assert body["policy_version"] is None
    assert body["policy_objections"] == ["repository_not_in_policy"]


def test_the_grant_is_two_named_classes_and_not_any_class(client, m2m):
    """The control on every affirmative test above: version 4 admits a NAMED second class.

    Had the class term been loosened rather than extended -- dropped, or turned into a truth
    test -- every factory assertion here would still pass while the policy approved anything a
    producer chose to write. This is the payload that tells those two versions apart.
    """
    body = client.post(
        "/api/deploy-changes",
        json=factory_conformant(change_class=_A_CLASS_NO_VERSION_ADMITS),
        headers=m2m,
    ).json()

    assert body["status"] == "pending"
    assert "change_class_not_in_policy" in body["policy_objections"]


def test_a_factory_record_is_held_to_the_same_criteria_as_any_other(client, m2m):
    """Admitting the class loosened nothing else, and the load-bearing term is the one to prove
    it on: criteria a human never ratified are refused whoever authored the change.

    This is also where the ceiling ADR-0025 records becomes visible. Criteria are keyed by
    REPOSITORY and classes are a flat set, so factory work is held to exactly the two criteria a
    lockfile bump is -- both statements about the deployment mechanism, so both true, and no way
    to require more of one than the other without keying criteria on repository and class
    together. That is a separate decision and is not made here.
    """
    body = client.post(
        "/api/deploy-changes",
        json=factory_conformant(acceptance_criteria=["something a human never ratified"]),
        headers=m2m,
    ).json()

    assert body["status"] == "pending"
    assert "acceptance_criteria_not_ratified" in body["policy_objections"]


def test_a_factory_approval_survives_a_separate_connection(file_engine):
    """The approval is COMMITTED, not merely returned.

    A file database and a second Session, for the reason the same assertion gives above: this
    repository's suite runs `:memory:` behind a `StaticPool`, which hands every session ONE
    connection, so a flushed-but-uncommitted row is visible to a "second session" there. The
    approval this test is about is the single authorization permitting a machine-authored change
    to reach production unattended, so a write that looks right and is discarded is exactly the
    failure worth spending a real database on.
    """
    with Session(file_engine) as writing:
        item, created = propose_deploy_change(writing, DeployChangeIn(**factory_conformant()))
        assert created and item.status == "approved"
        item_id = item.id

    with Session(file_engine) as other:
        stored = other.get(ChangeItem, item_id)
        assert stored is not None
        assert stored.status == "approved"
        assert stored.change_class == FACTORY_CLASS
        assert stored.policy_version == CURRENT_VERSION
        assert stored.decided_by == POLICY_ACTOR


def test_a_record_approved_under_version_three_still_means_what_it_meant():
    """Version 3 is retained VERBATIM, so an approval recorded under it stays re-derivable.

    The registry lookup alone would pass against an edited version 3, which is the failure the
    module's editing contract exists to prevent -- so the terms are asserted too, including the
    one version 4 changed. A record stamped 3 was approved for `dependency-update` and for
    nothing else, and that is still what looking version 3 up says.
    """
    v3 = policy_for(3)
    assert v3 is not None and v3 is not current()
    assert v3.version == 3 and v3.decided == "2026-08-15"
    assert v3.change_classes == frozenset({BOT_CLASS})
    assert FACTORY_CLASS not in v3.change_classes
    assert v3.repositories == {BRAIN, CHANGE_MANAGER}

    # A LITERAL, because V3 and V4 share the `_V3_BRAIN_CRITERIA` OBJECT -- so comparing
    # `v3.acceptance_criteria[BRAIN]` against `current()`'s compares a reference with itself and
    # passes even when that constant has been edited in place, which is the exact failure this
    # test's docstring names. Only a literal can see it.
    assert v3.acceptance_criteria[BRAIN] == (
        "the rollout runs for this merge on alobarquest/brain, and its production step "
        "concludes success (job 'deploy', step 'Deploy brain apps')",
        "every brain application this rollout triggered answered /api/health reporting the "
        "merged commit as its revision and a status of ok, within 600 seconds; an application "
        "whose Coolify UUID secret is unset is neither triggered nor checked, and a rollout "
        "that triggered none fails rather than passing empty",
    )


def test_version_four_did_not_widen_what_may_land():
    """A class grant is not a landing grant. ADR-0025's second boundary: policy approval means
    NO OBJECTION, never GO AHEAD, and every condition on the act is unchanged.

    WHAT THIS TEST DOES NOT ESTABLISH, stated because an earlier version of it claimed to. It is
    tempting to read "the update types are unchanged" as "so a factory pull request can never be
    landed by that lane". That inference is FALSE and was measured to be: the pattern reading a
    version delta out of a title is only END-anchored, so `SDS <unit>: Bump ruff from 0.15.20 to
    0.16.2` parses as `semver-patch` while `SDS <unit>: Reformat embedded code blocks` does not.
    A unit title is free text a human writes, so the separation would rest on wording.

    That lane selects subjects on approved status alone and asks nothing about the change class,
    so this version makes factory records visible to it for the first time. The refusal belongs
    there, keyed on the class this version names -- it is not a term this policy can express, and
    asserting it here would be this file vouching for a guarantee another repository owes.
    """
    v4 = policy_for(4)
    assert v4 is not None
    assert v4.version == 4
    assert v4.landing.update_types == frozenset({"semver-minor", "semver-patch"})
    assert v4.landing.excluded_ecosystems is None, "version 4 predates the outcome rule"
    assert v4.landing.require_head_current_with_base is True
    assert set(v4.landing.rollout_workflows) == {BRAIN, CHANGE_MANAGER}


# ---------------------------------------------------------------------------
# Version 5 -- what decides is the outcome (ADR-0036).
# ---------------------------------------------------------------------------


def test_version_five_changes_what_decides_and_nothing_else():
    """The version's whole claim, asserted term by term against the one it supersedes.

    ADR-0036 moves exactly one condition on the act. Every other term is version 4's own object,
    so a version that quietly widened a repository, a class, a criterion, a remedy or a pin while
    wearing this version's rationale would fail here.
    """
    v4, v5 = policy_for(4), policy_for(5)
    assert v4 is not None and v5 is not None
    # `v5 is current()` stood here until version 6 superseded it. The claim moved rather than
    # lapsed: `test_version_six_declares_a_second_population_and_changes_nothing_about_the_first`
    # anchors `current()`, and these tests chain version to version back to version 1, so
    # anchoring the newest anchors every one of them.

    assert v5.repositories == v4.repositories
    assert v5.change_classes == v4.change_classes
    assert v5.risks == v4.risks
    assert v5.acceptance_criteria == v4.acceptance_criteria
    assert v5.rollback_plans == v4.rollback_plans
    assert v5.landing.rollout_workflows == v4.landing.rollout_workflows
    assert v5.landing.require_head_current_with_base is True

    # The one thing that moves, in both directions: the delta stops deciding and the exclusion
    # starts being stated rather than inferred from one.
    assert v4.landing.excluded_ecosystems is None
    assert v5.landing.excluded_ecosystems == frozenset({GITHUB_ACTIONS})
    assert v5.landing.update_types == frozenset()


def test_the_excluded_ecosystem_is_spelled_the_way_a_BRANCH_spells_it():
    """An underscore, and this is not pedantry.

    The estate's other lane carries a gate revision that compared the HYPHENATED spelling against
    this exact value, matched nothing, and therefore permitted nothing while reading as though it
    permitted more. Its registry transcribes that literal rather than correcting it, so the defect
    stays visible. Here the spelling is what the landing party matches the second segment of a
    branch against, and getting it wrong would OVER-refuse -- the safe direction, and therefore
    the one nobody notices.
    """
    assert GITHUB_ACTIONS == "github_actions"
    assert current().landing.excluded_ecosystems == frozenset({"github_actions"})


def test_every_superseded_version_still_decides_by_update_type():
    """The editing contract, asserted over the field version 5 adds rather than only in prose.

    An approval stamped 1, 2, 3 or 4 was granted under a rule about version deltas. If any of
    them acquired an excluded set, looking that version up would report a decision nobody made --
    and the landing party keys the RULE IT APPLIES on exactly this field, so the edit would not
    merely misdescribe the past, it would change what a record approved under it may land.
    """
    for version in (1, 2, 3, 4):
        policy = policy_for(version)
        assert policy is not None
        assert policy.landing.excluded_ecosystems is None, version
        assert policy.landing.update_types == frozenset({"semver-minor", "semver-patch"}), version


def test_a_version_that_does_not_decide_on_the_outcome_OMITS_the_key():
    """Presence is what tells the landing party which rule to apply, so absence has to be real.

    Serving `[]` for versions 1 to 4 would say those versions exclude nothing -- true of the
    words and false of the rule, since they decide by update type and exclude by omission. The
    reader on the other side treats an absent key as the older rule and a present one as the
    outcome rule, so an always-served key would make every retained version look like version 5.
    """
    for version in (1, 2, 3, 4):
        policy = policy_for(version)
        assert policy is not None
        assert "excluded_ecosystems" not in landing_conditions_dict(policy), version

    assert landing_conditions_dict(current())["excluded_ecosystems"] == ["github_actions"]


def test_version_five_still_serves_update_types_as_a_floor_for_an_older_reader():
    """EMPTY, PRESENT, and well-typed -- and each of the three is load-bearing.

    The two sides of this contract are different processes that ship separately, so a landing
    party running the previous build reads these conditions. **Present and well-typed** because
    that reader parses the whole shape or none of it, and failing to parse refuses every record in
    both repositories rather than the ones this version is about. **Empty** because such a reader
    cannot see the rule above and must permit nothing under a version it does not understand.

    It is a floor for that reader and deliberately not a statement that version 5 permits no
    delta -- which is why the assertion lives beside the one above rather than in place of it.
    """
    served = landing_conditions_dict(current())

    assert served["update_types"] == []
    assert isinstance(served["update_types"], list)


def test_version_fives_rationale_records_the_decision_it_rests_on():
    """The `rationale` is the RECORD, and the only artifact a reader re-deriving this approval in
    a year will have. Pinned as a citation and a subject, never as prose."""
    v4, v5 = policy_for(4), policy_for(5)
    assert v4 is not None and v5 is not None
    assert "ADR-0036" in v5.landing.rationale
    assert v5.rationale != v4.rationale
    assert v5.landing.rationale != v4.landing.rationale


def test_a_record_approved_under_version_four_is_re_approved_under_the_version_in_force(
    client, m2m, db
):
    """The expected cost of any version bump, and it is a widening so it lifts by itself.

    The landing binds an approval to the version IN FORCE, so a record stamped 4 is refused there
    until re-approved. Every held record still conforms -- nothing about the shape a proposal must
    have moved -- so the producer's next pass re-stamps it and the binding lasts about an hour.

    Named for the version in force rather than for a number, because the property is what every
    bump costs and not what version 5 cost. Version 6 pays it again for the same reason: it adds
    a second population and moves no term a record must satisfy, so every held record still
    conforms and is re-stamped rather than stranded.
    """
    item_id = client.post("/api/deploy-changes", json=conformant(), headers=m2m).json()["id"]
    row = db.get(ChangeItem, item_id)
    assert row is not None
    row.policy_version = 4
    db.commit()

    served = client.get("/api/items?source=deploy", headers=m2m).json()[0]
    assert served["policy_version"] == 4
    assert served["landing_policy_version"] == CURRENT_VERSION

    replay = client.post("/api/deploy-changes", json=conformant(), headers=m2m)

    assert replay.json()["policy_version"] == CURRENT_VERSION
    assert replay.json()["policy_objections"] == []


def test_a_version_that_decides_on_the_outcome_EXCLUDES_SOMETHING():
    """An empty excluded set is the maximally permissive shape this schema can express, and it is
    one dropped element away from a version that means to exclude something.

    Note the asymmetry with the pin one field over, which is deliberate on both sides:
    `rollout_workflows` treats an absent entry as a REFUSAL, because nobody saying which bytes is
    not the same as those bytes being fine. Here an empty set is a real value the reader honours as
    "exclude nothing" -- so the guard against authoring it by accident belongs on this side, where
    the authoring happens, rather than on the side that must read whatever it is served.
    """
    for policy in REGISTRY.values():
        excluded = policy.landing.excluded_ecosystems
        if excluded is not None:
            assert excluded, f"version {policy.version} decides on the outcome and excludes nothing"


def test_a_version_cannot_declare_BOTH_rules():
    """One document, two readers, and this is what stops them being given two answers.

    A landing party that predates the outcome rule enforces `update_types`; one that has learned it
    ignores that field entirely. A version setting both -- the outcome rule, still capped at minor
    -- would therefore be enforced by the old reader and ignored by the new one, from the same
    served bytes. Pinning them mutually exclusive also pins version 5's empty floor, which is
    otherwise a convention in a comment.
    """
    for policy in REGISTRY.values():
        if policy.landing.excluded_ecosystems is not None:
            assert policy.landing.update_types == frozenset(), (
                f"version {policy.version} decides on the outcome and also names update types"
            )
        else:
            assert policy.landing.update_types, (
                f"version {policy.version} decides by update type and names none"
            )


# ---------------------------------------------------------------------------
# Version 6 -- the inert population declared beside the deploying one (ADR-0038).
# ---------------------------------------------------------------------------


def test_version_six_declares_a_second_population_and_changes_nothing_about_the_first():
    """The version's whole claim, asserted term by term against the one it supersedes.

    ADR-0038 adds a block and touches nothing keyed on the deploying population. A version that
    quietly widened a repository, a class, a risk, a criterion, a remedy, a pin or a condition on
    the deploying act while wearing this version's rationale would fail here.
    """
    v5, v6 = policy_for(5), policy_for(6)
    assert v5 is not None and v6 is not None
    assert v6 is current()

    assert v6.repositories == v5.repositories
    assert v6.change_classes == v5.change_classes
    assert v6.risks == v5.risks
    assert v6.acceptance_criteria == v5.acceptance_criteria
    assert v6.rollback_plans == v5.rollback_plans

    # The SAME OBJECT, not an equal one. Version 6 makes no new statement about the deploying
    # lane, so a re-transcription of its conditions would be a second copy of one judgment -- and
    # identity is the only assertion that catches a copy which happens to agree today.
    assert v6.landing is v5.landing

    # The one thing that moves.
    assert v5.inert_landing is None
    assert v6.inert_landing is not None


def test_the_two_populations_are_disjoint():
    """A repository named by both would be claimed by two landing lanes on different terms.

    Nothing downstream compares the two answers, so the one that ran is whichever lane looked
    first -- and they differ in whether a change record, acceptance criteria, a rollback plan and
    a change window are required. Stated over EVERY version rather than the current one, because a
    later version widening either set is exactly how the overlap would arrive.
    """
    for policy in REGISTRY.values():
        inert = policy.inert_landing
        if inert is None:
            continue
        overlap = policy.repositories & inert.repositories
        assert not overlap, f"version {policy.version} names {sorted(overlap)} in both populations"


def test_the_inert_population_is_the_six_that_carried_the_rule():
    """The population is a DECLARED LIST, which is what makes removing a member a version bump.

    `factory-runner` is the member that needed a ruling and is therefore the member worth pinning
    by name: ADR-0015 excluded it from the factory on a trust loop, and ADR-0038 part 1a records
    why that does not reach a lane which lands an update bot's version-number diff behind the one
    required check in this estate that admins cannot bypass.
    """
    inert = current().inert_landing
    assert inert is not None
    assert inert.repositories == frozenset(
        {
            "alobarquest/orchestrator",
            "alobarquest/intent-packages",
            "alobarquest/security-standards",
            "alobarquest/infraops-mcp-server",
            "alobarquest/project-standards",
            "alobarquest/factory-runner",
        }
    )
    assert "alobarquest/factory-runner" in inert.repositories


def test_the_inert_exclusion_is_docker_and_the_deploying_one_is_not():
    """One principle, two populations, two literals -- and the pair is the assertion.

    Asserting `docker` alone would pass just as well if somebody had copied the deploying lane's
    exclusion across, which is the mistake a reader arriving at one having read the other is most
    likely to make: exclude where the required checks do not exercise what changed, and the two
    populations fail to exercise different things. Pinning them DIFFERENT is what states that.

    The spelling is the second segment of the branch the update bot opens, read from a real
    branch (`dependabot/docker/python-3.14-slim`) rather than from a config file. It sits on the
    EXCLUDING side, so a member nothing matches excludes nothing and the landing party admits
    exactly the ecosystem this exists for -- the unsafe direction, which is why a test holds it.
    """
    policy = current()
    assert policy.inert_landing is not None

    assert DOCKER == "docker"
    assert policy.inert_landing.excluded_ecosystems == frozenset({"docker"})
    assert policy.landing.excluded_ecosystems == frozenset({"github_actions"})
    assert policy.inert_landing.excluded_ecosystems != policy.landing.excluded_ecosystems


def test_the_inert_lane_permits_the_update_bot_and_nobody_else():
    """The condition the workflow gated on FIRST, and the only thing bounding this lane's subjects.

    It is a field rather than a sentence in the rationale because the two readings of a
    prose-only condition are "apply something the document does not declare" and "drop it", and
    the second is a live fail-open: four of the six repositories declared here carry a factory
    caller workflow, so a machine-authored pull request with green checks is a real subject. This
    lane asks none of the questions the factory's own landing lane asks of one -- whether the unit
    completed, whether the verifier decided its criteria from observed evidence, whether an
    authority approval is bound to the envelope.

    Asserted as an EXACT set rather than as membership: `DEPENDABOT in permitted_authors` is
    satisfied by a version that permits everybody, which is the shape this exists to refuse.

    The spelling is `pull_request.user.login`'s and not `gh pr view --json author`'s, which
    answers `app/dependabot` for the same pull request. It permits rather than excludes, so a
    wrong value under-permits and the lane goes quiet -- the direction nobody notices, which is
    why a test holds it.
    """
    inert = current().inert_landing
    assert inert is not None

    assert DEPENDABOT == "dependabot[bot]"
    assert inert.permitted_authors == frozenset({"dependabot[bot]"})


def test_a_declared_inert_population_PERMITS_SOMEBODY_AND_NOT_EVERYBODY():
    """Both directions, because the two failures are opposite and only one is loud.

    An empty author set makes the lane land nothing, which somebody notices within a day. A set
    this schema cannot bound -- the failure a later author reaching for "any bot" would produce --
    lands anything, quietly. Stated over every version that declares a block, since a later
    version widening it is how either arrives.
    """
    for policy in REGISTRY.values():
        inert = policy.inert_landing
        if inert is None:
            continue
        assert inert.permitted_authors, f"version {policy.version} permits no author"
        assert inert.permitted_authors <= frozenset({DEPENDABOT}), (
            f"version {policy.version} permits an author nobody decided: "
            f"{sorted(inert.permitted_authors - {DEPENDABOT})}"
        )


def test_the_inert_lane_requires_freshness():
    """A TIGHTENING over the workflow this replaces, which required nothing.

    Branch protection is `strict: false` estate-wide and deliberately so, so nothing else asks
    this. It is also what serialises the lane, which is why no pace condition accompanies it --
    and the absence of one is asserted below rather than left to the rationale.
    """
    inert = current().inert_landing
    assert inert is not None
    assert inert.require_head_current_with_base is True


def test_the_inert_block_declares_nothing_the_deploying_lane_owns():
    """The fields ARE the whole of what this document says about the act for this population.

    A landing party may not add a condition this block does not state and may not drop one it
    does, so the field set is the contract. Acceptance criteria, a remedy, a rollout pin, a change
    window and a pace are every one of them a statement about something already serving, and this
    population has nothing serving -- declaring any of them, even as empty or false, would record
    a decision nobody made. Stated as a field-set equality so that ADDING one is what fails,
    which is the direction a later increment would drift in.
    """
    from dataclasses import fields

    inert = current().inert_landing
    assert inert is not None
    assert {f.name for f in fields(inert)} == {
        "repositories",
        "permitted_authors",
        "excluded_ecosystems",
        "require_head_current_with_base",
        "rationale",
    }


def test_every_superseded_version_declares_no_inert_population():
    """The editing contract, asserted over the field version 6 adds rather than only in prose.

    An approval stamped 1 to 5 was granted by a document that said nothing about a second
    population. If any of them acquired one, looking that version up would report a decision
    nobody made -- and because the landing party keys WHETHER IT HAS A LANE AT ALL on this field's
    presence, the edit would not merely misdescribe the past, it would open a lane under a version
    that never had one.
    """
    for version in (1, 2, 3, 4, 5):
        policy = policy_for(version)
        assert policy is not None
        assert policy.inert_landing is None, version


def test_a_version_that_declares_no_inert_population_OMITS_the_key():
    """Presence is what tells the landing party it has a second lane, so absence has to be real.

    Serving an empty block for versions 1 to 5 would say those versions considered this lane and
    admitted nobody to it. They considered nothing. The reader must fail closed on an absent key,
    and an always-served block would make every retained version look like version 6 with an empty
    population -- a different statement, reached by a different decision, that nobody made.
    """
    for version in (1, 2, 3, 4, 5):
        policy = policy_for(version)
        assert policy is not None
        assert inert_landing_dict(policy) is None, version

    assert inert_landing_dict(current()) is not None


def test_a_declared_inert_population_IS_NOT_EMPTY():
    """An empty population is one dropped element away from a block that means to admit somebody.

    The guard belongs on this side, where the authoring happens, rather than on the side that must
    read whatever it is served -- the same asymmetry `excluded_ecosystems` carries one field over.
    An empty exclusion set is refused for the mirror-image reason: it is the maximally permissive
    shape this schema can express, and here it would admit the base-image ecosystem the whole
    block exists to hold out.
    """
    for policy in REGISTRY.values():
        inert = policy.inert_landing
        if inert is None:
            continue
        assert inert.repositories, f"version {policy.version} declares an empty inert population"
        assert inert.excluded_ecosystems, f"version {policy.version} excludes nothing"


def test_version_sixs_rationale_records_the_decision_it_rests_on():
    """The `rationale` is the RECORD, and the only artifact a reader re-deriving this in a year
    will have. Pinned as a citation and as the two subjects it must not lose."""
    v5, v6 = policy_for(5), policy_for(6)
    assert v5 is not None and v6 is not None
    assert v6.inert_landing is not None

    assert "ADR-0038" in v6.rationale
    assert "ADR-0038" in v6.inert_landing.rationale
    assert v6.rationale != v5.rationale

    # The two subjects a later edit is most likely to drop, because each answers a question a
    # reader will otherwise re-litigate: why this ecosystem and not the other one, and why there
    # is no pace condition beside a freshness condition.
    assert "docker" in v6.inert_landing.rationale
    assert "pace" in v6.inert_landing.rationale


def test_the_served_body_omits_the_inert_block_for_a_version_that_declares_none():
    """The omission asserted where it is REACHABLE, which is not through either route.

    A route only ever serves `current()`, so no test through HTTP can reach a version that
    declares no inert population -- and that is precisely the case the omission exists for. The
    branch would therefore be unkillable if this were tested only at the routes: a mutation
    serving the key unconditionally would pass everything, while a later version that dropped the
    block would start telling every reader it had a lane with nobody in it.

    That is why `policy_dict` is in the policy module rather than beside the routes.
    """
    for version in (1, 2, 3, 4, 5):
        policy = policy_for(version)
        assert policy is not None
        assert "inert_landing" not in policy_dict(policy), version

    assert "inert_landing" in policy_dict(current())


def test_the_policy_route_serves_the_inert_population(client, m2m):
    declared = current().inert_landing
    assert declared is not None
    body = client.get("/api/deploy-policy", headers=m2m).json()
    assert body["version"] == CURRENT_VERSION
    assert body["inert_landing"]["permitted_authors"] == ["dependabot[bot]"]
    assert body["inert_landing"]["excluded_ecosystems"] == ["docker"]
    assert body["inert_landing"]["require_head_current_with_base"] is True

    # THE RATIONALE REACHES THE WIRE, which nothing asserted until adversarial review mutated it
    # to the empty string and watched the whole suite pass. It is the only artifact a reader
    # re-deriving this in a year has, and a served block that lost it would still carry every
    # term -- so the omission is invisible in exactly the direction that matters.
    assert body["inert_landing"]["rationale"] == declared.rationale
    assert "ADR-0038" in body["inert_landing"]["rationale"]
    assert "alobarquest/factory-runner" in body["inert_landing"]["repositories"]
    assert len(body["inert_landing"]["repositories"]) == 6

    # The deploying half of the same response, unchanged and beside it -- so a change that served
    # the new block by displacing the old one fails here rather than in production.
    assert body["repositories"] == ["alobarquest/brain", "alobarquest/change-manager"]
    assert body["landing"]["excluded_ecosystems"] == ["github_actions"]


def test_both_policy_routes_serve_the_same_document(client, m2m):
    """TWO PROJECTIONS OF ONE HOLDER, and this is the assertion that keeps it true.

    ADR-0038. The second path exists because the party that lands cannot spell the first -- its
    architecture guards forbid the bare token that path is spelled with, and its own rule is to
    reword rather than to widen a guard, which a URL cannot be. Two routes composing their own
    bodies would be the second holder ADR-0038 rejected, so they share `current()` and one
    builder, and equality here is what a drift between them would fail.
    """
    a = client.get("/api/deploy-policy", headers=m2m)
    b = client.get("/api/landing-policy", headers=m2m)

    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json() == b.json()
    assert b.json()["inert_landing"]["excluded_ecosystems"] == ["docker"]


def test_the_second_policy_route_requires_a_credential(client):
    assert client.get("/api/landing-policy").status_code == 401
