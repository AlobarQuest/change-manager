from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_m2m
from app.db import get_db
from app.models import ChangeItem
from app.reconcile import reconcile
from app.schemas import SyncRequest, SyncSummary

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
