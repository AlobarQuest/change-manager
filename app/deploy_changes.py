"""Propose a deploying-merge change (ADR-0019).

The one ingress that CREATES a `ChangeItem` without deriving it from an infrastructure
scan. `reconcile` — the only other construction site — answers "what is drifting right
now?"; this answers "here is a change somebody intends to make", which no scan will
ever report. `app.sources` explains what that difference costs and how it is guarded.

The drift vocabulary is not reused to carry deploy facts. `plan` and `handoff` are set
by this module to their empty forms and are not accepted from the caller: a free-form
JSON blob would take the acceptance criteria and the rollback plan back out of columns
that can be refused, which is the whole point of ADR-0019 recording them.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

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

# The facts the proposer asserts. A retry carrying all of them unchanged is the same
# proposal; a retry that differs in any of them is a different one, and is refused
# rather than silently ignored. `actor` is deliberately absent: it says who called,
# not what the change is.
_PROPOSED_FIELDS = (
    "target_repository",
    "pull_request_number",
    "change_class",
    "risk",
    "reasoning",
    "acceptance_criteria",
    "rollback_plan",
    "note",
)


class DeployChangeConflict(Exception):
    """A record already exists for this pull request, asserting different facts."""

    def __init__(self, item_id: int, differing: list[str]) -> None:
        super().__init__(
            f"a deploy change already exists for this pull request (item {item_id}) "
            f"asserting different {', '.join(differing)}"
        )
        self.item_id = item_id
        self.differing = differing


def _proposed(body: DeployChangeIn) -> dict:
    values = body.model_dump()
    values["rollback_plan"] = body.rollback_plan.model_dump()
    return {field: values[field] for field in _PROPOSED_FIELDS}


def propose_deploy_change(db: Session, body: DeployChangeIn) -> tuple[ChangeItem, bool]:
    """Record a proposed deploying merge. Returns (item, created).

    `created` is False when an identical proposal already exists — a caller that lost
    our response can retry. Raises DeployChangeConflict when one exists asserting
    different facts. We commit.
    """
    proposed = _proposed(body)
    identity = deploy_identity(body.target_repository, body.pull_request_number)

    existing = db.scalar(select(ChangeItem).where(ChangeItem.identity == identity))
    if existing is not None:
        differing = [f for f in _PROPOSED_FIELDS if getattr(existing, f) != proposed[f]]
        if differing:
            raise DeployChangeConflict(existing.id, differing)
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
    db.flush()
    record_event(
        db,
        item,
        actor=body.actor,
        event_type="proposed",
        to_status="pending",
        detail=f"deploying merge proposed: {identity}",
    )
    db.commit()
    return item, True
