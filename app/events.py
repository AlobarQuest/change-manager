from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import ChangeEvent, ChangeItem


def record_event(
    db: Session,
    item: ChangeItem,
    *,
    actor: str,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
    detail: str | None = None,
    attempt_id: int | None = None,
    window_run_id: int | None = None,
) -> ChangeEvent:
    """Append one immutable history row. The caller commits."""
    ev = ChangeEvent(
        item_id=item.id,
        at=datetime.now(UTC),
        actor=actor,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        detail=detail,
        attempt_id=attempt_id,
        window_run_id=window_run_id,
    )
    db.add(ev)
    return ev
