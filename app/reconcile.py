from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.events import record_event
from app.identity import rule_key_of, stable_identity
from app.models import ChangeItem
from app.schemas import SyncRequest, SyncSummary

# Statuses that mean "this drift is settled / closed" and should reopen if it reappears.
_CLOSED = {"done", "resolved"}


def reconcile(db: Session, req: SyncRequest) -> SyncSummary:
    now = datetime.now(timezone.utc)
    new = refreshed = resolved = reopened = 0

    seen_identities: set[str] = set()

    for e in req.escalations:
        rule_key = rule_key_of(e.proposal_id)
        identity = stable_identity(e.instance, rule_key, e.target.uuid)
        seen_identities.add(identity)
        urgent = e.urgent or e.reasoning.startswith("[URGENT]")

        item = db.scalar(select(ChangeItem).where(ChangeItem.identity == identity))
        if item is None:
            item = ChangeItem(
                identity=identity, instance=e.instance, rule_key=rule_key,
                provider=e.target.provider, resource_type=e.target.resource_type,
                resource_uuid=e.target.uuid, resource_name=e.target.name,
                risk=e.risk, kind=e.kind, reasoning=e.reasoning, plan=e.plan, note=e.note,
                status="pending", first_seen_at=now, last_seen_at=now,
                source_report=req.source_report, source=req.source, urgent=urgent,
            )
            db.add(item)
            db.flush()
            record_event(db, item, actor="sync", event_type="ingested", to_status="pending",
                         detail=f"first seen in {req.source_report}")
            new += 1
            continue

        # Existing: always refresh the latest plan/note/last_seen/source/urgent.
        item.plan, item.note = e.plan, e.note
        item.last_seen_at, item.source_report = now, req.source_report
        item.source, item.urgent = req.source, urgent

        if item.status in _CLOSED:
            prev = item.status
            item.status = "pending"
            item.decided_by = None
            item.decided_at = None
            record_event(db, item, actor="sync", event_type="regression_reopened",
                         from_status=prev, to_status="pending",
                         detail="drift reappeared after it was closed")
            reopened += 1
        else:
            refreshed += 1  # pending/approved/deferred/blocked/failed/wontfix/in_progress: decision stands

    # Items in the queue but NOT in this report → resolved (drift cleared), except wontfix.
    # SCOPED to this sync's source: a security sync must not resolve drift items, and
    # vice-versa — otherwise the two pipelines clobber each other's queues.
    open_items = db.scalars(
        select(ChangeItem).where(
            ChangeItem.status.notin_(["resolved", "wontfix"]),
            ChangeItem.source == req.source,
        )
    ).all()
    for item in open_items:
        if item.identity not in seen_identities:
            prev = item.status
            item.status = "resolved"
            record_event(db, item, actor="sync", event_type="resolved",
                         from_status=prev, to_status="resolved", detail="no longer flagged")
            resolved += 1

    db.commit()
    return SyncSummary(new=new, refreshed=refreshed, resolved=resolved, reopened=reopened)
