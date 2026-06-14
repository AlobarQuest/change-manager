from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_m2m
from app.db import get_db
from app.events import record_event
from app.models import ChangeAttempt, ChangeItem
from app.reconcile import reconcile
from app.schemas import DecisionIn, OutcomeIn, SyncRequest, SyncSummary

router = APIRouter(prefix="/api", dependencies=[Depends(require_m2m)])


def _item_dict(it: ChangeItem) -> dict:
    return {
        "id": it.id, "identity": it.identity, "instance": it.instance, "rule_key": it.rule_key,
        "resource_type": it.resource_type, "resource_uuid": it.resource_uuid,
        "resource_name": it.resource_name, "risk": it.risk, "kind": it.kind,
        "reasoning": it.reasoning, "plan": it.plan, "note": it.note, "status": it.status,
        "decided_by": it.decided_by,
    }


@router.post("/sync", response_model=SyncSummary)
def sync(req: SyncRequest, db: Session = Depends(get_db)) -> SyncSummary:
    return reconcile(db, req)


@router.get("/items")
def list_items(
    status: str | None = Query(default=None),
    instance: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(ChangeItem)
    if status:
        stmt = stmt.where(ChangeItem.status == status)
    if instance:
        stmt = stmt.where(ChangeItem.instance == instance)
    return [_item_dict(it) for it in db.scalars(stmt.order_by(ChangeItem.id)).all()]


@router.get("/items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    return _item_dict(it)


# outcome → resulting item status + the event type to record
_OUTCOME_STATUS = {
    "done": ("done", "attempt_done"),
    "failed": ("failed", "attempt_failed"),
    "blocked": ("blocked", "attempt_blocked"),
    "skipped_conformant": ("resolved", "resolved"),
}


@router.post("/items/{item_id}/claim")
def claim(item_id: int, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    if it.status != "approved":
        raise HTTPException(status_code=409, detail=f"not approved (status={it.status})")
    it.status = "in_progress"
    record_event(db, it, actor="executor", event_type="claimed",
                 from_status="approved", to_status="in_progress")
    db.commit()
    return _item_dict(it)


@router.post("/items/{item_id}/outcome")
def outcome(item_id: int, body: OutcomeIn, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    if body.outcome not in _OUTCOME_STATUS:
        raise HTTPException(status_code=422, detail=f"unknown outcome {body.outcome}")
    new_status, event_type = _OUTCOME_STATUS[body.outcome]
    now = datetime.now(timezone.utc)
    attempt = ChangeAttempt(item_id=it.id, started_at=now, finished_at=now,
                            outcome=body.outcome, detail=body.detail,
                            tool_calls=body.tool_calls, rollback=body.rollback)
    db.add(attempt)
    db.flush()
    prev = it.status
    it.status = new_status
    record_event(db, it, actor="executor", event_type=event_type,
                 from_status=prev, to_status=new_status, detail=body.detail, attempt_id=attempt.id)
    db.commit()
    return _item_dict(it)


def _decide(db: Session, item_id: int, body: DecisionIn, new_status: str, event_type: str) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    prev = it.status
    it.status = new_status
    it.decided_by = body.actor
    it.decided_at = datetime.now(timezone.utc)
    record_event(db, it, actor=body.actor, event_type=event_type,
                 from_status=prev, to_status=new_status, detail=body.detail)
    db.commit()
    return _item_dict(it)


@router.post("/items/{item_id}/approve")
def approve(item_id: int, body: DecisionIn, db: Session = Depends(get_db)) -> dict:
    return _decide(db, item_id, body, "approved", "approved")


@router.post("/items/{item_id}/defer")
def defer(item_id: int, body: DecisionIn, db: Session = Depends(get_db)) -> dict:
    return _decide(db, item_id, body, "deferred", "deferred")


@router.post("/items/{item_id}/wontfix")
def wontfix(item_id: int, body: DecisionIn, db: Session = Depends(get_db)) -> dict:
    return _decide(db, item_id, body, "wontfix", "wontfixed")


@router.post("/items/{item_id}/reactivate")
def reactivate(item_id: int, body: DecisionIn, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    if it.status != "wontfix":
        raise HTTPException(status_code=409, detail=f"reactivate only from wontfix (status={it.status})")
    return _decide(db, item_id, body, "pending", "reactivated")
