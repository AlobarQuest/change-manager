from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.events import record_event
from app.models import ChangeItem
from app.sources import POLICY_APPROVED_SOURCES


class TransitionError(Exception):
    """An invalid status transition (e.g. reactivate from a non-wontfix item)."""


def decide(
    db: Session,
    item: ChangeItem,
    *,
    actor: str,
    new_status: str,
    event_type: str,
    detail: str | None = None,
) -> None:
    """Apply a human decision: set status + decider + history event. We commit.

    APPROVING A PROPOSED CHANGE IS NOT A DECISION ANY CALLER MAKES (ADR-0019 increment 5).
    The guard is here, on the write, rather than only on the routes, because this function
    has six callers -- five API verbs and the GUI -- and a guard placed on the doors is a
    guard a seventh caller does not inherit. This repository learned that in increment 1,
    where every guard was keyed on `source` while the write joined on `identity`.

    Only the grant is refused. The vetoes reach this function with a different
    `new_status` and are untouched, which is the asymmetry Devon asked for: policy grants,
    a human revokes.

    KEYED ON `POLICY_APPROVED_SOURCES`, NOT ON `PROPOSED_SOURCES`, AND THE DIFFERENCE IS THE
    WHOLE OF ADR-0026'S CARRY. This refusal says "a pinned policy decides this, so there is no
    approval for a caller to perform" -- which is true of a deploying merge and false of a work
    proposal, whose entire point is that a human approves it here. Keyed on the wider set, a
    work record could be proposed and could never be approved by anybody, and the failure would
    read as a deliberate guard rather than as the accident it is. `app/sources.py` carries the
    three-property argument.
    """
    if new_status == "approved" and item.source in POLICY_APPROVED_SOURCES:
        raise TransitionError(
            f"'{item.source}' changes are approved by policy conformance, not by a caller "
            f"(item {item.id})"
        )
    prev = item.status
    item.status = new_status
    item.decided_by = actor
    item.decided_at = datetime.now(UTC)
    record_event(
        db,
        item,
        actor=actor,
        event_type=event_type,
        from_status=prev,
        to_status=new_status,
        detail=detail,
    )
    db.commit()


def reactivate(db: Session, item: ChangeItem, *, actor: str, detail: str | None = None) -> None:
    """wontfix → pending. Raises TransitionError if the item isn't wontfix."""
    if item.status != "wontfix":
        raise TransitionError(f"reactivate only from wontfix (status={item.status})")
    decide(db, item, actor=actor, new_status="pending", event_type="reactivated", detail=detail)


def hand_off(db: Session, item: ChangeItem, *, actor: str, detail: str | None = None) -> None:
    """pending|blocked → handed_off.

    Records actor + handed_off_at. Raises if not pending/blocked.
    """
    if item.status not in ("pending", "blocked"):
        raise TransitionError(f"hand off only from pending|blocked (status={item.status})")
    prev = item.status
    now = datetime.now(UTC)
    item.status = "handed_off"
    item.decided_by = actor
    item.decided_at = now
    item.handed_off_at = now
    record_event(
        db,
        item,
        actor=actor,
        event_type="handed_off",
        from_status=prev,
        to_status="handed_off",
        detail=detail,
    )
    db.commit()
