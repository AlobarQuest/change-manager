from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ChangeEvent, ChangeItem, WindowRun
from app.templates_env import templates
from app.transitions import TransitionError, decide, hand_off
from app.transitions import reactivate as do_reactivate
from app.web_auth import current_user

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    status: str = Query(default="pending"),
    source: str = Query(default="all"),
    user: str = Depends(current_user),
    db: Session = Depends(get_db),
):
    # Urgent (security) items sort first, then by id.
    stmt = select(ChangeItem).order_by(ChangeItem.urgent.desc(), ChangeItem.id)
    if status != "all":
        stmt = stmt.where(ChangeItem.status == status)
    if source != "all":
        stmt = stmt.where(ChangeItem.source == source)
    items = db.scalars(stmt).all()
    return templates.TemplateResponse(
        request, "dashboard.html",
        {"items": items, "current_status": status, "current_source": source, "user": user},
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


_ACTIONS = {  # gui action → (new_status, event_type)
    "approve": ("approved", "approved"),
    "defer": ("deferred", "deferred"),
    "wontfix": ("wontfix", "wontfixed"),
    "resolve": ("resolved", "resolved"),  # human "mark done": handled out-of-band, close it
}


@router.post("/items/{item_id}/{action}")
def item_action(
    request: Request, item_id: int, action: str,
    user: str = Depends(current_user), db: Session = Depends(get_db),
):
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    if action == "reactivate":
        try:
            do_reactivate(db, it, actor=user)
        except TransitionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
    elif action == "handoff":
        try:
            hand_off(db, it, actor=user)
        except TransitionError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
    elif action in _ACTIONS:
        new_status, event_type = _ACTIONS[action]
        decide(db, it, actor=user, new_status=new_status, event_type=event_type)
    else:
        raise HTTPException(status_code=400, detail=f"unknown action {action}")
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, "_row.html", {"it": it, "user": user})
    return RedirectResponse(url=f"/items/{item_id}", status_code=303)


@router.get("/windows")
def windows(request: Request, user: str = Depends(current_user), db: Session = Depends(get_db)):
    runs = db.scalars(select(WindowRun).order_by(WindowRun.id.desc())).all()
    return templates.TemplateResponse(request, "windows.html", {"runs": runs, "user": user})
