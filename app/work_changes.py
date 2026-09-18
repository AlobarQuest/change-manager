"""The ingress for work proposed to the software delivery system (ADR-0026).

**This is the join between the two halves of the Operations Factory.** change-manager is
where a thing goes when it needs a person to decide; the orchestrator is what does the work.
Until now nothing carried an approved item from one to the other, so change-manager stopped
at "we approved the work" and the orchestrator started at a human pasting JSON into a form.

**What this module deliberately does NOT do, and the two are different absences.**

It does not APPROVE. A work record is created `pending` and a human approves it, through the
ordinary decision routes, exactly as ADR-0026 decision 5 says. That is why `work` is in
`PROPOSED_SOURCES` and NOT in `POLICY_APPROVED_SOURCES` -- the deploy pipeline's policy is
about deploying merges and has nothing to say about a package revision, and being governed by
a policy that cannot see you is indistinguishable from having no approver at all.

It does not EXECUTE, and nothing here can. `work` is in `PROPOSED_SOURCES`, so the record is
withheld from the unfiltered `GET /api/items?status=approved` the 04:00 change-window executor
calls, and `claim`/`outcome`/`handoff` refuse it at `require_executor`. That matters more here
than it did for a deploying merge: the executor hands what it lists to an LLM agent holding
production Coolify tools, and its own filter is a denylist, so a source it predates arrives by
default. Withholding it server-side is what makes that safe, rather than a hope about a
program in another repository.

**THE PRODUCER IS `bump_proposer`, AND THIS PARAGRAPH USED TO SAY THERE WAS NONE.** ADR-0026
recorded that the thing which reads a refusal and concludes what package would fix it did not
exist, and that was true when it was written; ADR-0028 built it. The orchestrator's
`bump_proposer` runs on a schedule, proposes a record per outstanding dependency bump, and
REPLAYS every record it has already proposed on every pass. That is what makes the replay
rules below load-bearing rather than theoretical, and it is why a field added to
`_ASSERTED_FIELDS` is a decision about every record already in the database. An operator and
the tests are still callers; they stopped being the only ones.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.events import record_event
from app.identity import work_identity
from app.models import ChangeItem
from app.schemas import WorkChangeIn
from app.sources import WORK_LANE, WORK_SOURCE

# The rule that produced the item, in the same slot drift uses for the rule it fired.
WORK_RULE_KEY = "work-proposal"
# A work proposal is about a package revision, not about a deployed instance. Naming it keeps
# `GET /api/events` free of new nulls for its adapter, exactly as `DEPLOY_INSTANCE` does.
WORK_INSTANCE = "sds"
# What kind of change item this is. Distinct from a deploying merge, which is what lands; this
# is what gets built.
WORK_KIND = "work_proposal"

# The facts the proposer ASSERTS about the work. A retry carrying all of them unchanged is the
# same proposal; a retry that differs in any of them is a different one, and is refused rather
# than silently ignored. `actor` is deliberately absent: it says who called, not what the work
# is. Note `package_id`/`package_revision`/`package_source_repository` are asserted too even
# though they are in the identity -- the identity is case-folded, so two proposals differing
# only in the case of a stored value share a key and must not silently overwrite each other.
#
# `originating_observation_id` IS ALSO ABSENT, FOR A DIFFERENT REASON THAN `actor`, AND THE
# DIFFERENCE IS THE WHOLE DECISION. `actor` is excluded because it is not about the work.
# The originating observation IS about the work -- it is the cause the signal->work contract
# requires the record to name -- and it is excluded because of what this tuple DOES.
#
# This tuple feeds exactly two things: the construction payload below, and the field-by-field
# comparison in `_existing` that decides replay from `WorkChangeConflict`. It does NOT
# re-assert anything onto an existing record -- `_existing` returns the row unmutated and
# `propose_work_change` returns it untouched, so there is no write path a repeat proposal can
# reach. (The deploy sibling DOES have one, over its `_DERIVED_FIELDS`; this lane has no
# derived facts and therefore no refresh.) So the only consequence of adding a field here is
# the comparison, and for this field that consequence is permanent: every record proposed
# before the column existed stores null, `bump_proposer` replays all of them on every pass,
# and a null-versus-id comparison would 409 each one forever -- which its caller classifies
# as a refusal, i.e. a finding, on every pass, with no repair route. A work record is
# write-once, its status is a human's alone, and no supersede route exists.
#
# THE COST, STATED PLAINLY BECAUSE IT IS REAL: a producer that named the wrong cause cannot
# correct it. A re-proposal naming a different observation answers 200 and the first cause
# stands. That is the same silence a differing `actor` already gets, and it is the side of the
# trade that does not wedge a scheduled producer permanently.
_ASSERTED_FIELDS = (
    "package_id",
    "package_revision",
    "package_source_repository",
    "risk",
    "reasoning",
    "note",
)


class WorkChangeConflict(Exception):
    """A different work proposal already exists for this package revision."""

    def __init__(self, item_id: int, differing: list[str]) -> None:
        super().__init__(
            f"a different work proposal already exists for this package revision "
            f"(item {item_id}); it differs in: {', '.join(differing)}"
        )
        self.item_id = item_id
        self.differing = differing


class WorkChangeIdentityHeld(Exception):
    """The identity this proposal would take belongs to another pipeline's record."""

    def __init__(self, item_id: int, source: str) -> None:
        super().__init__(
            f"identity is held by a '{source}' change (item {item_id}), "
            f"which a work proposal may not adopt"
        )
        self.item_id = item_id
        self.source = source


def propose_work_change(db: Session, body: WorkChangeIn) -> tuple[ChangeItem, bool]:
    """Record proposed work. Returns (item, created). We commit.

    `created` is False when an identical proposal already exists -- a caller that lost our
    response can retry. Raises `WorkChangeConflict` when one exists asserting different facts,
    and `WorkChangeIdentityHeld` when the key belongs to another pipeline.

    A repeat proposal is a genuine no-op here, unlike the deploy ingress: there is no policy to
    re-run and no derived field to refresh, because everything this record carries is asserted
    by the caller and none of it moves on its own.
    """
    proposed = {field: getattr(body, field) for field in _ASSERTED_FIELDS}
    identity = work_identity(body.package_source_repository, body.package_id, body.package_revision)

    existing = _existing(db, identity, proposed)
    if existing is not None:
        return existing, False

    now = datetime.now(UTC)
    item = ChangeItem(
        identity=identity,
        instance=WORK_INSTANCE,
        rule_key=WORK_RULE_KEY,
        kind=WORK_KIND,
        source=WORK_SOURCE,
        lane=WORK_LANE,
        status="pending",
        plan={},
        first_seen_at=now,
        last_seen_at=now,
        # Written explicitly because it is deliberately NOT in `_ASSERTED_FIELDS`, which is
        # also the construction payload -- see that tuple's comment. It is set once, here,
        # and no path updates it afterwards.
        originating_observation_id=body.originating_observation_id,
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
            detail=f"work proposed: {identity}",
        )
        db.commit()
    except IntegrityError:
        # A concurrent proposal for the same package revision won the unique index between our
        # SELECT and our INSERT. That is the retry this function promises to support, so it
        # must not surface as a 500: roll back and answer from the row that landed -- replay if
        # it says the same thing, conflict if it does not.
        db.rollback()
        winner = _existing(db, identity, proposed)
        if winner is None:  # pragma: no cover - the row cannot vanish again
            raise
        return winner, False
    return item, True


def _existing(db: Session, identity: str, proposed: dict) -> ChangeItem | None:
    """The record this proposal is a repeat of, or None. Raises on a real conflict."""
    item = db.scalar(select(ChangeItem).where(ChangeItem.identity == identity))
    if item is None:
        return None
    if item.source != WORK_SOURCE:
        # `change_items.identity` is unique across every pipeline, and the drift scheme
        # (f"{instance}::{rule_key}::{uuid}") can spell a work identity. The mirror of
        # reconcile's refusal, and of the deploy ingress's: it will not adopt ours, and we will
        # not adopt its. Without this the field-by-field comparison below reports every work
        # column as "differing", which is fail-closed but unreadable.
        raise WorkChangeIdentityHeld(item.id, item.source)
    differing = [f for f in _ASSERTED_FIELDS if getattr(item, f) != proposed[f]]
    if differing:
        raise WorkChangeConflict(item.id, differing)
    return item
