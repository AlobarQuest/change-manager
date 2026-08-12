"""Retire a deploying-merge record whose subject is gone (ADR-0019 increment 5b).

A record proposed for a pull request that was later CLOSED UNMERGED stands for a change that can
never happen. Production item 44 is the live case: it records `AlobarQuest/change-manager` #42,
closed unmerged on 2026-08-11 and superseded by #48, and it was approved by a human before the
policy existed. Nothing retires it, so an approved record sits in the estate authorising a landing
that has no subject.

WHY THIS IS A ROUTE AND NOT `resolve`. `transitions.decide` would accept it -- only `approved` is
refused for a proposed source -- but `POST /api/items/{item_id}/resolve` is a status-moving route
and is reachable by the FULL credential alone (`app/scopes.py`). The producer that can see the
pull request closed holds the `propose` scope, and giving it the general resolve verb would let it
terminate any record of any pipeline. This route is narrower in three ways at once: it works on
deploy records only, it takes no status from the caller, and its only outcome is `resolved`.

WHY IT IS SAFE TO ACT ON A FACT THIS SERVICE CANNOT CHECK, which increment 3 refused to do for
policy. The difference is DIRECTION. Increment 3's fail-open was a caller-declared fact that would
have GRANTED permission; a retirement can only ever remove it. A caller that lied here could stop
a landing it was going to be able to make anyway, and could not cause one: the record becomes
terminal, `identity` stays held so no fresh record can be proposed for the same pull request, and
`resolved` is not a status any landing term accepts. Availability, not authority -- and the
producer is the only holder of that scope.

The event says WHY, naming the pull request, because a machine resolving a decision a human made
is only honest if the chain reads: a person approved it, the subject went away, the producer
retired it.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.events import record_event
from app.models import ChangeItem
from app.sources import DEPLOY_SOURCE

# The one observation this route accepts. A closed vocabulary of exactly one member, because the
# route's whole justification is that its outcome cannot be chosen: a second observation with a
# different outcome would be a different route with a different argument behind it.
CLOSED_UNMERGED = "pull_request_closed_unmerged"
OBSERVATIONS = frozenset({CLOSED_UNMERGED})

# Already terminal. A repeat is a replay rather than an error, because the producer sweeps every
# pass and a retirement it already made must not become a finding.
_TERMINAL = frozenset({"resolved", "wontfix"})

RETIRED_STATUS = "resolved"
RETIRED_EVENT = "retired"


class RetirementRefused(Exception):
    """The record is not one this route may retire, or the observation does not match it."""


def retire_deploy_change(
    db: Session,
    item: ChangeItem,
    *,
    observation: str,
    pull_request_number: int,
    actor: str,
) -> bool:
    """Retire the record. Returns whether it moved; False means it was already terminal.

    Every guard is a positive check rather than an absence: the record must be a deploy record,
    the observation must be the one member of the vocabulary, and the pull request the caller
    names must be the one the record is about. A caller that names a different pull request is
    refused rather than having its number ignored -- the number is what makes the retirement
    about a subject the caller actually observed, so dropping it would leave the route retiring
    records on nothing but an item id.
    """
    if item.source != DEPLOY_SOURCE:
        raise RetirementRefused(
            f"item {item.id} is a '{item.source}' change; this route retires "
            f"'{DEPLOY_SOURCE}' records only"
        )
    if observation not in OBSERVATIONS:
        raise RetirementRefused(f"{observation!r} is not an observation this route accepts")
    if item.pull_request_number != pull_request_number:
        raise RetirementRefused(
            f"item {item.id} is about pull request {item.pull_request_number}, "
            f"not {pull_request_number}"
        )
    if item.status in _TERMINAL:
        return False

    prev = item.status
    item.status = RETIRED_STATUS
    # `decided_by` is a latest-writer column by decision (Devon, 2026-08-12): it answers who is
    # answerable for the record's current state, and `change_events` answers how it got there. So
    # a retirement records the producer, and Devon's approval of item 44 stays legible in the
    # chain rather than in this column.
    item.decided_by = actor
    item.decided_at = datetime.now(UTC)
    record_event(
        db,
        item,
        actor=actor,
        event_type=RETIRED_EVENT,
        from_status=prev,
        to_status=RETIRED_STATUS,
        detail=(
            f"{item.target_repository}#{pull_request_number} was closed without merging, so the "
            "change this record stands for can no longer happen; retired against that fact "
            "rather than against its absence"
        ),
    )
    db.commit()
    return True
