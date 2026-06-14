from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ChangeEvent, ChangeItem
from app.templates_env import templates
from app.web_auth import current_user

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    status: str = Query(default="pending"),
    user: str = Depends(current_user),
    db: Session = Depends(get_db),
):
    stmt = select(ChangeItem).order_by(ChangeItem.id)
    if status != "all":
        stmt = stmt.where(ChangeItem.status == status)
    items = db.scalars(stmt).all()
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"items": items, "current_status": status, "user": user},
    )


@router.get("/items/{item_id}")
def item_detail(
    request: Request, item_id: int,
    user: str = Depends(current_user), db: Session = Depends(get_db),
):
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    events = db.scalars(
        select(ChangeEvent).where(ChangeEvent.item_id == item_id).order_by(ChangeEvent.id)
    ).all()
    return templates.TemplateResponse(
        request, "item_detail.html", {"it": it, "events": events, "user": user},
    )
