"""Propose a deploying-merge change, and approve it by policy (ADR-0019).

The one ingress that CREATES a `ChangeItem` without deriving it from an infrastructure
scan. `reconcile` — the only other construction site — answers "what is drifting right
now?"; this answers "here is a change somebody intends to make", which no scan will
ever report. `app.sources` explains what that difference costs and how it is guarded.

The drift vocabulary is not reused to carry deploy facts. `plan` and `handoff` are set
by this module to their empty forms and are not accepted from the caller: a free-form
JSON blob would take the acceptance criteria and the rollback plan back out of columns
that can be refused, which is the whole point of ADR-0019 recording them.

INCREMENT 5 ADDS THE APPROVAL, AND IT HAPPENS HERE OR NOWHERE. `_apply_policy` is the
only path by which a deploying-merge record reaches `approved`; every route that could
once do it now refuses, and so does the write beneath them. Approval is therefore not an
act a credential performs but a property the server observes — which is Devon's ruling
that the human act is setting the policy, made mechanical.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deploy_policy import current as current_policy
from app.deploy_policy import objections
from app.events import record_event
from app.identity import deploy_identity
from app.models import ChangeItem
from app.schemas import DeployChangeIn
from app.sources import DEPLOY_LANE, DEPLOY_SOURCE

# The rule that produced the item, in the same slot drift uses for the rule it fired.
DEPLOY_RULE_KEY = "deploying-merge"
# ADR-0019 governs deploys to PRODUCTION systems, so the instance is not a caller
# choice. Naming it keeps `GET /api/events` free of new nulls for its adapter.
DEPLOY_INSTANCE = "prod"
# What kind of change item this is, as distinct from `change_class`, which is what
# kind of change is landing (a dependency update, a software delivery).
DEPLOY_KIND = "deploying_merge"

# The facts the proposer ASSERTS about the change. A retry carrying all of them unchanged
# is the same proposal; a retry that differs in any of them is a different one, and is
# refused rather than silently ignored. `actor` is deliberately absent: it says who called,
# not what the change is.
_ASSERTED_FIELDS = (
    "target_repository",
    "pull_request_number",
    "change_class",
    "risk",
    "reasoning",
    "note",
)

# The facts the proposer DERIVES from the world, which are REFRESHED on a repeat proposal
# rather than compared.
#
# THIS SPLIT IS A FIX, NOT A CONVENIENCE, AND THE BUG IT CLOSES WAS PERMANENT. When these
# two lived with the asserted facts, a rollout workflow change made every later proposal
# differ, so each existing record 409'd and kept its OLD criteria forever — and once the
# policy was bumped to the new criteria, those records could never conform again. There was
# no route back: the row is write-once, `PATCH` accepts only `pr_url`, no supersede route
# exists, and the identity stays held so a fresh record cannot be created either. A single
# rollout-workflow merge would have silently and permanently revoked every waiting record.
#
# Refreshing is the honest treatment because these fields are DERIVED: they state what the
# rollout workflow currently attests and how the repository is currently put back, rather
# than making a claim the caller is answerable for. A refresh is recorded as an event and
# re-runs the policy, so a record whose criteria move out from under its approval is
# revoked rather than left asserting something nobody ratified.
_DERIVED_FIELDS = (
    "acceptance_criteria",
    "rollback_plan",
)

_PROPOSED_FIELDS = _ASSERTED_FIELDS + _DERIVED_FIELDS

# The statuses the policy may move, enumerated as what it MAY change rather than what it
# may not. That polarity is the fail-closed one: a status nobody has thought about —
# `in_progress`, `handed_off`, `failed` — is left alone, where a denylist would silently
# admit it. A human's decision (`deferred`, `wontfix`, `resolved`) is never overridden:
# policy grants, and a human revokes.
_POLICY_MAY_MOVE = frozenset({"pending", "approved"})

# The approver written into `decided_by` and, through the events feed, into the estate's
# tamper-evident chain as the grant's approver. It names the MECHANISM, because there is no
# person and no credential behind it — conformance to a version a human pinned is what
# decided. The version travels in `policy_version` and in the event detail rather than in
# this string, so the actor stays one stable identity the registry can resolve.
POLICY_ACTOR = "deploy-policy"


class DeployChangeConflict(Exception):
    """A record already exists for this pull request, asserting different facts."""

    def __init__(self, item_id: int, differing: list[str]) -> None:
        super().__init__(
            f"a deploy change already exists for this pull request (item {item_id}) "
            f"asserting different {', '.join(differing)}"
        )
        self.item_id = item_id
        self.differing = differing


class DeployChangeIdentityHeld(Exception):
    """This pull request's identity is already held by a record of another pipeline."""

    def __init__(self, item_id: int, source: str) -> None:
        super().__init__(f"identity for this pull request is held by a '{source}' item ({item_id})")
        self.item_id = item_id
        self.source = source


def _proposed(body: DeployChangeIn) -> dict:
    values = body.model_dump()
    values["rollback_plan"] = body.rollback_plan.model_dump()
    return {field: values[field] for field in _PROPOSED_FIELDS}


def _existing(db: Session, identity: str, proposed: dict) -> ChangeItem | None:
    """The record this proposal is a repeat of, or None. Raises on a real conflict."""
    item = db.scalar(select(ChangeItem).where(ChangeItem.identity == identity))
    if item is None:
        return None
    if item.source != DEPLOY_SOURCE:
        # `change_items.identity` is unique across every pipeline, and the drift
        # scheme (f"{instance}::{rule_key}::{uuid}") can spell a deploy identity. The
        # mirror of reconcile's refusal: it will not adopt ours, and we will not adopt
        # its. Without this the field-by-field comparison below reports every deploy
        # column as "differing", which is fail-closed but unreadable.
        raise DeployChangeIdentityHeld(item.id, item.source)
    differing = [f for f in _ASSERTED_FIELDS if getattr(item, f) != proposed[f]]
    if differing:
        raise DeployChangeConflict(item.id, differing)
    return item


def _refresh_derived(db: Session, item: ChangeItem, proposed: dict, actor: str) -> list[str]:
    """Bring the derived facts up to date, recording it. Returns the fields that moved."""
    moved = [field for field in _DERIVED_FIELDS if getattr(item, field) != proposed[field]]
    if not moved:
        return []
    for field in moved:
        setattr(item, field, proposed[field])
    record_event(
        db,
        item,
        actor=actor,
        event_type="criteria_refreshed",
        detail=(
            f"what the rollout attests, or how it is undone, has moved: {', '.join(moved)}; "
            "the record now carries the current derivation and is re-evaluated against policy"
        ),
    )
    return moved


def _apply_policy(db: Session, item: ChangeItem) -> None:
    """Approve, or revoke, by conformance to the current policy. THE ONLY APPROVAL PATH.

    No route reaches this and no caller chooses its outcome: the server runs it inside the
    proposal transaction and conformance decides. That is what makes "no credential can
    approve a deploying-merge record" true of the WRITE rather than only of the door — and
    the doors are closed too, in `guards.require_policy_approver` and `transitions.decide`.

    IT WRITES RATHER THAN DERIVING ON READ, and an earlier design did the opposite. Three
    things killed that, each independently sufficient. `change.approved` is the only event
    this service emits that becomes an `authority_grant` in the estate's tamper-evident
    chain, so a status computed at read time would have left the single authorization
    permitting an autonomous production deploy as the one decision absent from it, while a
    trivial drift approval still entered. The listing applies `status` as a SQL predicate
    on the stored column, so a derived answer would have selected the wrong rows in both
    directions. And a record must carry the version it was decided under, or an approval
    stops being re-derivable the moment the policy moves — which is the property the
    estate's own rule pin already has, and the one the derived design had dropped.
    """
    if item.status not in _POLICY_MAY_MOVE:
        return
    policy = current_policy()
    found = objections(policy, item)
    now = datetime.now(UTC)

    if not found and item.status != "approved":
        item.status = "approved"
        item.decided_by = POLICY_ACTOR
        item.decided_at = now
        item.policy_version = policy.version
        record_event(
            db,
            item,
            actor=POLICY_ACTOR,
            event_type="approved",
            from_status="pending",
            to_status="approved",
            detail=(
                f"conforms to deploy policy v{policy.version}, pinned {policy.decided}; "
                "approved by that policy rather than by any caller"
            ),
        )
        return

    if not found and item.status == "approved" and item.policy_version != policy.version:
        # STILL CONFORMS, UNDER A NEWER VERSION. Without this branch the record is stranded on the
        # version that approved it: the branch above needs `status != "approved"` and the one
        # below needs an objection, so a conforming approved record matches NEITHER -- and there
        # is no other route, because `approve` is refused to every caller including the full
        # bearer and the identity is held so no fresh record can be proposed. The landing binds an
        # approval to the version in force, so a stranded record becomes permanently unlandable.
        #
        # It is a NEW GRANT and emits the event that says so. A version bump is a fresh human
        # decision about what may land unattended, and `approved` is the only thing this service
        # emits that enters the estate's tamper-evident chain -- re-stamping the column silently
        # would leave the grant under version 2 absent from it while the one under version 1 is
        # there.
        previous = item.policy_version
        item.decided_by = POLICY_ACTOR
        item.decided_at = now
        item.policy_version = policy.version
        record_event(
            db,
            item,
            actor=POLICY_ACTOR,
            event_type="approved",
            from_status="approved",
            to_status="approved",
            detail=(
                f"still conforms under deploy policy v{policy.version}, pinned {policy.decided}; "
                f"re-approved from v{previous} rather than left on the version that has been "
                "superseded"
            ),
        )
        return

    if found and item.status == "approved":
        # Approved under criteria that have since moved. Leaving it approved would let it
        # assert conformance to something nobody ratified, so it goes back to pending and
        # says why. Fail closed: policy revokes only what policy granted.
        item.status = "pending"
        item.decided_by = POLICY_ACTOR
        item.decided_at = now
        item.policy_version = None
        record_event(
            db,
            item,
            actor=POLICY_ACTOR,
            event_type="policy_revoked",
            from_status="approved",
            to_status="pending",
            detail=(
                f"no longer conforms to deploy policy v{policy.version}: {', '.join(found)}; "
                "a human ratifies the change by bumping the policy version"
            ),
        )


def propose_deploy_change(db: Session, body: DeployChangeIn) -> tuple[ChangeItem, bool]:
    """Record a proposed deploying merge. Returns (item, created).

    `created` is False when an identical proposal already exists — a caller that lost
    our response can retry. Raises DeployChangeConflict when one exists asserting
    different facts. We commit.
    """
    proposed = _proposed(body)
    identity = deploy_identity(body.target_repository, body.pull_request_number)

    existing = _existing(db, identity, proposed)
    if existing is not None:
        # A repeat proposal is where a policy bump takes effect and where a moved rollout
        # workflow is noticed, so it is not a no-op even when nothing the caller said has
        # changed. The producer runs hourly; this is what makes that cadence do work.
        _refresh_derived(db, existing, proposed, body.actor)
        _apply_policy(db, existing)
        db.commit()
        return existing, False

    now = datetime.now(UTC)
    item = ChangeItem(
        identity=identity,
        instance=DEPLOY_INSTANCE,
        rule_key=DEPLOY_RULE_KEY,
        kind=DEPLOY_KIND,
        source=DEPLOY_SOURCE,
        lane=DEPLOY_LANE,
        status="pending",
        plan={},
        first_seen_at=now,
        last_seen_at=now,
        **proposed,
    )
    db.add(item)
    try:
        db.flush()
        record_event(
            db,
            item,
            actor=body.actor,
            event_type="proposed",
            to_status="pending",
            detail=f"deploying merge proposed: {identity}",
        )
        _apply_policy(db, item)
        db.commit()
    except IntegrityError:
        # A concurrent proposal for the same pull request won the unique index between
        # our SELECT and our INSERT. That is the retry this function promises to
        # support, so it must not surface as a 500: roll back and answer from the row
        # that landed — replay if it says the same thing, conflict if it does not.
        db.rollback()
        winner = _existing(db, identity, proposed)
        if winner is None:  # pragma: no cover - the row cannot vanish again
            raise
        return winner, False
    return item, True
