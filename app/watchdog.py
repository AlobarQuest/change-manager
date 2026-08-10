from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events import record_event
from app.models import ChangeItem
from app.sources import PROPOSED_SOURCES


def revert_stale_handoffs(
    db: Session, *, now: datetime, source: str, seen_identities: set[str], max_age_days: int
) -> int:
    """Revert handed_off items (of `source`) older than max_age_days that are STILL flagged
    (present in this sync) back to pending. Absent stale items are left for reconcile's
    resolve pass (the app conformed). The caller commits.

    Proposed items are excluded structurally rather than left to reconcile's refusal:
    "unreachable because its only caller checks first" is not a property a future
    caller inherits."""
    cutoff = now - timedelta(days=max_age_days)
    reverted = 0
    stale = db.scalars(
        select(ChangeItem).where(
            ChangeItem.status == "handed_off",
            ChangeItem.source == source,
            ChangeItem.source.notin_(sorted(PROPOSED_SOURCES)),
            ChangeItem.handed_off_at < cutoff,
        )
    ).all()
    for item in stale:
        if item.identity not in seen_identities:
            continue
        item.status = "pending"
        item.decided_by = None
        item.decided_at = None
        record_event(
            db,
            item,
            actor="watchdog",
            event_type="handoff_watchdog_reverted",
            from_status="handed_off",
            to_status="pending",
            detail=f"handoff unresolved after {max_age_days}d — reverted to pending",
        )
        reverted += 1
    if reverted:
        db.flush()
    return reverted
