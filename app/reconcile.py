from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.events import record_event
from app.identity import rule_key_of, stable_identity
from app.models import ChangeItem
from app.schemas import SyncRequest, SyncSummary
from app.sources import PROPOSED_SOURCES, ProposedSourceError
from app.watchdog import revert_stale_handoffs

# Statuses that mean "this drift is settled / closed" and should reopen if it reappears.
_CLOSED = {"done", "resolved"}


def _resolve_absent(db: Session, *, source: str, seen_identities: set[str]) -> int:
    """Items in the queue but NOT in this report → resolved (drift cleared), except wontfix.

    SCOPED to this sync's source: a security sync must not resolve drift items, and
    vice-versa — otherwise the two pipelines clobber each other's queues. Proposed
    items are excluded on top of that, because absence from a scan is what "the drift
    cleared" MEANS and a proposal is absent from every scan there will ever be.

    Split out from `reconcile` so that exclusion can be asserted at the level where it
    is true. `reconcile` refuses a proposed source before reaching here, so a test
    driving `reconcile` cannot tell whether this clause is present — which is how a
    guard ends up resting entirely on a check in its caller. The caller commits.
    """
    resolved = 0
    open_items = db.scalars(
        select(ChangeItem).where(
            ChangeItem.status.notin_(["resolved", "wontfix"]),
            ChangeItem.source == source,
            ChangeItem.source.notin_(sorted(PROPOSED_SOURCES)),
        )
    ).all()
    for item in open_items:
        if item.identity not in seen_identities:
            prev = item.status
            item.status = "resolved"
            record_event(
                db,
                item,
                actor="sync",
                event_type="resolved",
                from_status=prev,
                to_status="resolved",
                detail="no longer flagged",
            )
            resolved += 1
    return resolved


def reconcile(db: Session, req: SyncRequest) -> SyncSummary:
    # `source` is caller-declared free text, so nothing but this stops a drift-shaped
    # batch from claiming a proposed pipeline's namespace and reconciling records it
    # did not produce. Refused here rather than in the route so a direct caller of
    # reconcile() cannot get round it either.
    if req.source in PROPOSED_SOURCES:
        raise ProposedSourceError(
            f"'{req.source}' items are proposed, not derived — they cannot be reconciled "
            "from a scan batch"
        )

    now = datetime.now(UTC)
    new = refreshed = reopened = 0

    seen_identities: set[str] = set()

    for e in req.escalations:
        rule_key = rule_key_of(e.proposal_id)
        identity = stable_identity(e.instance, rule_key, e.target.uuid)
        seen_identities.add(identity)
        urgent = e.urgent or e.reasoning.startswith("[URGENT]")

        item = db.scalar(select(ChangeItem).where(ChangeItem.identity == identity))
        if item is None:
            item = ChangeItem(
                identity=identity,
                instance=e.instance,
                rule_key=rule_key,
                provider=e.target.provider,
                resource_type=e.target.resource_type,
                resource_uuid=e.target.uuid,
                resource_name=e.target.name,
                risk=e.risk,
                kind=e.kind,
                reasoning=e.reasoning,
                plan=e.plan,
                note=e.note,
                handoff_brief=e.handoff_brief,
                lane=e.lane,
                handoff=e.handoff,
                status="pending",
                first_seen_at=now,
                last_seen_at=now,
                source_report=req.source_report,
                source=req.source,
                urgent=urgent,
            )
            db.add(item)
            db.flush()
            record_event(
                db,
                item,
                actor="sync",
                event_type="ingested",
                to_status="pending",
                detail=f"first seen in {req.source_report}",
            )
            new += 1
            continue

        # Existing: always refresh the latest plan/note/last_seen/source/urgent.
        item.plan, item.note = e.plan, e.note
        item.handoff_brief = e.handoff_brief
        item.lane, item.handoff = e.lane, e.handoff
        item.last_seen_at, item.source_report = now, req.source_report
        item.source, item.urgent = req.source, urgent

        if item.status in _CLOSED:
            prev = item.status
            item.status = "pending"
            item.decided_by = None
            item.decided_at = None
            record_event(
                db,
                item,
                actor="sync",
                event_type="regression_reopened",
                from_status=prev,
                to_status="pending",
                detail="drift reappeared after it was closed",
            )
            reopened += 1
        else:
            # pending/approved/deferred/blocked/failed/wontfix/in_progress: decision stands
            refreshed += 1

    # Watchdog (reuses this scheduled sync execution; no new scheduler): stale, still-flagged
    # handed_off items revert to pending so a forgotten handoff resurfaces.
    revert_stale_handoffs(
        db,
        now=now,
        source=req.source,
        seen_identities=seen_identities,
        max_age_days=settings.handoff_watchdog_days,
    )

    resolved = _resolve_absent(db, source=req.source, seen_identities=seen_identities)

    db.commit()
    return SyncSummary(new=new, refreshed=refreshed, resolved=resolved, reopened=reopened)
