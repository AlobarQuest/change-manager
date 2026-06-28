from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_m2m
from app.db import get_db
from app.events import record_event
from app.models import ChangeAttempt, ChangeItem, WindowRun
from app.reconcile import reconcile
from app.schemas import DecisionIn, OutcomeIn, SyncRequest, SyncSummary
from app.transitions import TransitionError
from app.transitions import decide as _do_decide
from app.transitions import hand_off as _do_hand_off
from app.transitions import reactivate as _do_reactivate

router = APIRouter(prefix="/api", dependencies=[Depends(require_m2m)])


def _item_dict(it: ChangeItem) -> dict:
    return {
        "id": it.id, "identity": it.identity, "instance": it.instance, "rule_key": it.rule_key,
        "resource_type": it.resource_type, "resource_uuid": it.resource_uuid,
        "resource_name": it.resource_name, "risk": it.risk, "kind": it.kind,
        "reasoning": it.reasoning, "plan": it.plan, "note": it.note, "status": it.status,
        "source": it.source, "urgent": it.urgent, "decided_by": it.decided_by,
        "handoff_brief": it.handoff_brief,
        "handed_off_at": it.handed_off_at.isoformat() if it.handed_off_at else None,
        "lane": it.lane, "handoff": it.handoff, "pr_url": it.pr_url,
    }


@router.post("/sync", response_model=SyncSummary)
def sync(req: SyncRequest, db: Session = Depends(get_db)) -> SyncSummary:
    return reconcile(db, req)


@router.get("/items")
def list_items(
    status: str | None = Query(default=None),
    instance: str | None = Query(default=None),
    source: str | None = Query(default=None),
    lane: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(ChangeItem)
    if status:
        stmt = stmt.where(ChangeItem.status == status)
    if instance:
        stmt = stmt.where(ChangeItem.instance == instance)
    if source:
        stmt = stmt.where(ChangeItem.source == source)
    if lane:
        stmt = stmt.where(ChangeItem.lane == lane)
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
    now = datetime.now(UTC)
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
    _do_decide(db, it, actor=body.actor, new_status=new_status, event_type=event_type, detail=body.detail)
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


@router.post("/items/{item_id}/resolve")
def resolve(item_id: int, body: DecisionIn, db: Session = Depends(get_db)) -> dict:
    # Human "mark done": this was handled/completed out-of-band; close it.
    # Distinct from wontfix (accepted risk). reconcile treats `resolved` as terminal.
    return _decide(db, item_id, body, "resolved", "resolved")


@router.post("/items/{item_id}/reactivate")
def reactivate(item_id: int, body: DecisionIn, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        _do_reactivate(db, it, actor=body.actor, detail=body.detail)
    except TransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _item_dict(it)


@router.post("/items/{item_id}/handoff")
def handoff(item_id: int, body: DecisionIn, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        _do_hand_off(db, it, actor=body.actor, detail=body.detail)
    except TransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _item_dict(it)


@router.get("/items/{item_id}/handoff")
def get_handoff(item_id: int, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None or not it.handoff:
        raise HTTPException(status_code=404, detail="no handoff for this item")
    return {"item_id": it.id, **it.handoff, "pr_url": it.pr_url}


class ItemPatch(BaseModel):
    pr_url: str | None = None


@router.patch("/items/{item_id}")
def patch_item(item_id: int, body: ItemPatch, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    if body.pr_url is not None:
        it.pr_url = body.pr_url
        record_event(db, it, actor="api", event_type="pr_linked",
                     detail=f"PR linked: {body.pr_url}")
    db.commit()
    return _item_dict(it)


class WindowStart(BaseModel):
    started_at: str  # ISO; stored as-is via fromisoformat


class WindowPatch(BaseModel):
    status: str | None = None
    considered: int | None = None
    applied: int | None = None
    failed: int | None = None
    blocked: int | None = None
    skipped: int | None = None
    report_md: str | None = None


def _window_dict(w: WindowRun) -> dict:
    return {"id": w.id, "status": w.status, "considered": w.considered, "applied": w.applied,
            "failed": w.failed, "blocked": w.blocked, "skipped": w.skipped}


@router.post("/window-runs")
def create_window(body: WindowStart, db: Session = Depends(get_db)) -> dict:
    started = datetime.fromisoformat(body.started_at.replace("Z", "+00:00"))
    w = WindowRun(started_at=started, status="running")
    db.add(w)
    db.commit()
    return _window_dict(w)


@router.patch("/window-runs/{window_id}")
def patch_window(window_id: int, body: WindowPatch, db: Session = Depends(get_db)) -> dict:
    w = db.get(WindowRun, window_id)
    if w is None:
        raise HTTPException(status_code=404, detail="not found")
    for field in ("status", "considered", "applied", "failed", "blocked", "skipped", "report_md"):
        val = getattr(body, field)
        if val is not None:
            setattr(w, field, val)
    if body.status in {"done", "error"}:
        w.finished_at = datetime.now(UTC)
    db.commit()
    return _window_dict(w)
