from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ChangeItem
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
