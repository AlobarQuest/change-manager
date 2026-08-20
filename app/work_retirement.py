"""Retire a work record whose work is done (ADR-0029).

A `work` record is a human's decision that a bump should be built (ADR-0026). Nothing moved it
out of `approved` when the build finished, so an approved record sat in the estate asking for
work that had already happened. Production item 61 is the live case:
`infraops-mcp-server-npm-eslint` revision 1, whose work unit completed and whose pull request
merged on 2026-08-19, and which still read `approved` the next morning.

Two consequences, and the quiet one is the reason this exists. The carry re-selects the record on
every pass forever and eventually reports a permanent finding; and, worse, an approved-and-done
record is indistinguishable from an approved-and-waiting one, so "what has been approved but not
yet built?" has no correct answer.

WHY THIS IS A ROUTE, WHERE THE DEPLOY SOURCE'S SUCCESS DIRECTION IS NOT. `app/deploy_settlement.py`
closes the matching half for a deploying merge and needs no route, because this server DERIVES the
fact: `verdict` and `production_reached` are computed here from coordinates the caller already
supplied. This server cannot derive "the work unit completed" and never will -- it has no
orchestrator egress, by design. So the fact is visible only to the caller and needs a door through
which to declare it. The direction is settlement's; the shape is retirement's.

WHY IT IS SAFE TO ACT ON A FACT THIS SERVICE CANNOT CHECK, which is `app/deploy_retirement.py`'s
argument and transfers unchanged. The difference is DIRECTION: a retirement can only ever REMOVE
permission. A caller that lied here would stop work that was going to be carried anyway, and could
not cause any -- the record becomes terminal, `identity` stays held so no fresh proposal can be
made for the same package revision, and `resolved` is not a status the carry selects on.

RETIRE ON COMPLETION, NOT ON SETTLEMENT, and the vocabulary's one member says so. A `failed` unit
may still be retried, so retiring on "no longer in flight" would terminate a record whose work is
still live. A `cancelled` unit is a human's decision and the matching record decision stays a
human's -- that is what happened to item 60, set to `wontfix` by hand. The machine acts on exactly
one fact and declines every neighbouring one.

`resolved` rather than `wontfix`: `app/api.py`'s own comment draws the line -- *"Distinct from
wontfix (accepted risk)."* The work was done, which is not a risk anybody accepted.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.events import record_event
from app.models import ChangeItem
from app.sources import WORK_SOURCE

# The one observation this route accepts. A closed vocabulary of exactly one member, because the
# route's whole justification is that its outcome cannot be chosen: the caller reports a fact and
# the server decides the status. A second observation with a different outcome would be a
# different route with a different argument behind it.
WORK_UNIT_COMPLETED = "work_unit_completed"
OBSERVATIONS = frozenset({WORK_UNIT_COMPLETED})

# Already terminal. A repeat is a replay rather than an error, because the producer sweeps every
# pass and a retirement it already made must not become a finding. Mirrors
# `deploy_retirement._TERMINAL` and `deploy_settlement._TERMINAL` exactly, so every way a record
# can be closed agrees about what is already closed.
_TERMINAL = frozenset({"resolved", "wontfix"})

RETIRED_STATUS = "resolved"
RETIRED_EVENT = "retired"


class WorkRetirementRefused(Exception):
    """The record is not one this route may retire, or the observation does not match it."""


def retire_work_change(
    db: Session,
    item: ChangeItem,
    *,
    observation: str,
    package_id: str,
    package_revision: int,
    actor: str,
) -> bool:
    """Retire the record. Returns whether it moved; False means it was already terminal.

    Every guard is a positive check rather than an absence: the record must be a work record, the
    observation must be the one member of the vocabulary, and the package revision the caller
    names must be the one the record is about.

    THE LOCATOR IS CHECKED, NOT TAKEN ON TRUST FROM THE PATH, for the reason the deploying-merge
    retirement checks its pull request number: naming the subject twice is what makes the
    retirement about something the caller actually observed. Without it this route retires
    whichever record an item id happened to select, and a producer that had resolved the wrong
    identifier one step earlier would close a record nobody looked at. `package_source_repository`
    is deliberately NOT part of the check -- `package_id` and `package_revision` already name the
    revision the orchestrator answered about, and a third field would refuse a caller that
    disagreed only about case, which `app/identity.py` case-folds anyway.
    """
    if item.source != WORK_SOURCE:
        raise WorkRetirementRefused(
            f"item {item.id} is a '{item.source}' change; this route retires "
            f"'{WORK_SOURCE}' records only"
        )
    if observation not in OBSERVATIONS:
        raise WorkRetirementRefused(f"{observation!r} is not an observation this route accepts")
    if item.package_id != package_id or item.package_revision != package_revision:
        raise WorkRetirementRefused(
            f"item {item.id} is about {item.package_id} revision {item.package_revision}, "
            f"not {package_id} revision {package_revision}"
        )
    if item.status in _TERMINAL:
        return False

    prev = item.status
    item.status = RETIRED_STATUS
    # `decided_by` is a latest-writer column by decision (Devon, 2026-08-12): it answers who is
    # answerable for the record's current state, and `change_events` answers how it got there. So
    # a retirement records the producer, and the human approval that caused the work stays legible
    # in the chain rather than in this column.
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
            f"the work this record asked for was built: {item.package_id} revision "
            f"{item.package_revision} completed in the software delivery system, so the record "
            "is retired against that fact rather than against its absence"
        ),
    )
    db.commit()
    return True
