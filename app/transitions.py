from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.events import record_event
from app.models import ChangeItem


class TransitionError(Exception):
    """An invalid status transition (e.g. reactivate from a non-wontfix item)."""


def decide(db: Session, item: ChangeItem, *, actor: str, new_status: str,
           event_type: str, detail: str | None = None) -> None:
    """Apply a human decision: set status + decider + history event. We commit."""
    prev = item.status
    item.status = new_status
    item.decided_by = actor
    item.decided_at = datetime.now(timezone.utc)
    record_event(db, item, actor=actor, event_type=event_type,
                 from_status=prev, to_status=new_status, detail=detail)
    db.commit()


def reactivate(db: Session, item: ChangeItem, *, actor: str, detail: str | None = None) -> None:
    """wontfix → pending. Raises TransitionError if the item isn't wontfix."""
    if item.status != "wontfix":
        raise TransitionError(f"reactivate only from wontfix (status={item.status})")
    decide(db, item, actor=actor, new_status="pending", event_type="reactivated", detail=detail)
