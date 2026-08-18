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

**There is no producer.** ADR-0026 says so outright -- the thing that reads a refusal and
concludes what package would fix it is a diagnosis step, and none exists or is specced. Today
this route's callers are an operator and the tests, which is where `POST /api/deploy-changes`
began too, before increment 5a gave it one. Recording that plainly is better than a comment
implying a caller that is not there.
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
