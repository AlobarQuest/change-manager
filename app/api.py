from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_m2m
from app.db import get_db
from app.deploy_changes import (
    DeployChangeConflict,
    DeployChangeIdentityHeld,
    propose_deploy_change,
)
from app.deploy_observations import (
    DeployObservationRefused,
    current_observation,
    merge_commits_observed,
    observations_for,
    record_deploy_observation,
)
from app.events import record_event
from app.models import ChangeAttempt, ChangeEvent, ChangeItem, DeployObservation, WindowRun
from app.reconcile import reconcile
from app.schemas import (
    ClaimIn,
    DecisionIn,
    DeployChangeIn,
    DeployObservationIn,
    OutcomeIn,
    SyncRequest,
    SyncSummary,
)
from app.sources import PROPOSED_SOURCES, ProposedSourceError
from app.transitions import TransitionError
from app.transitions import decide as _do_decide
from app.transitions import hand_off as _do_hand_off
from app.transitions import reactivate as _do_reactivate

router = APIRouter(prefix="/api", dependencies=[Depends(require_m2m)])


def _item_dict(it: ChangeItem) -> dict:
    return {
        "id": it.id,
        "identity": it.identity,
        "instance": it.instance,
        "rule_key": it.rule_key,
        "resource_type": it.resource_type,
        "resource_uuid": it.resource_uuid,
        "resource_name": it.resource_name,
        "risk": it.risk,
        "kind": it.kind,
        "reasoning": it.reasoning,
        "plan": it.plan,
        "note": it.note,
        "status": it.status,
        "source": it.source,
        "urgent": it.urgent,
        "decided_by": it.decided_by,
        "handoff_brief": it.handoff_brief,
        "handed_off_at": it.handed_off_at.isoformat() if it.handed_off_at else None,
        "lane": it.lane,
        "handoff": it.handoff,
        "pr_url": it.pr_url,
        "target_repository": it.target_repository,
        "pull_request_number": it.pull_request_number,
        "change_class": it.change_class,
        "acceptance_criteria": it.acceptance_criteria,
        "rollback_plan": it.rollback_plan,
    }


@router.post("/sync", response_model=SyncSummary)
def sync(req: SyncRequest, db: Session = Depends(get_db)) -> SyncSummary:
    try:
        return reconcile(db, req)
    except ProposedSourceError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


@router.post("/deploy-changes", status_code=201)
def propose_deploy(body: DeployChangeIn, response: Response, db: Session = Depends(get_db)) -> dict:
    """Propose a deploying merge (ADR-0019) — the ingress that does not derive.

    201 when the record is created, 200 when an identical proposal already existed,
    409 when a different one did. Nothing consults the record yet: the factory-lane
    admission term is increment 3 and the required-status-check gate is increment 4.
    """
    try:
        item, created = propose_deploy_change(db, body)
    except (DeployChangeConflict, DeployChangeIdentityHeld) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    response.status_code = 201 if created else 200
    return _item_dict(item)


def _observation_dict(ob: DeployObservation) -> dict:
    return {
        "id": ob.id,
        "item_id": ob.item_id,
        "observation_key": ob.observation_key,
        "merge_commit_sha": ob.merge_commit_sha,
        "merged_at": ob.merged_at.isoformat(),
        "verdict": ob.verdict,
        "production_reached": ob.production_reached,
        "workflow_path": ob.workflow_path,
        "workflow_revision": ob.workflow_revision,
        "workflow_attestation": ob.workflow_attestation,
        "rollout_job": ob.rollout_job,
        "rollout_job_conclusion": ob.rollout_job_conclusion,
        "trigger_step": ob.trigger_step,
        "trigger_step_conclusion": ob.trigger_step_conclusion,
        "concurrent_run_id": ob.concurrent_run_id,
        "run_id": ob.run_id,
        "run_attempt": ob.run_attempt,
        "run_url": ob.run_url,
        "run_conclusion": ob.run_conclusion,
        "run_concluded_at": ob.run_concluded_at.isoformat() if ob.run_concluded_at else None,
        "observed_at": ob.observed_at.isoformat(),
        "observed_by": ob.observed_by,
        "recorded_at": ob.recorded_at.isoformat(),
    }


@router.post("/items/{item_id}/deploy-observation", status_code=201)
def observe_deploy(
    item_id: int,
    body: DeployObservationIn,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    """Record what a watcher saw of the rollout this merge caused (ADR-0019 increment 2).

    NOT an outcome, and deliberately not on the execution lifecycle: it writes no
    `ChangeAttempt` and moves the item's status by exactly nothing. Increment 1 closed
    `claim`/`outcome`/`handoff` to proposed sources — the doors that let something assert it had
    APPLIED a change — and this route does not reopen them, because observing is not applying.
    Whether the change is finished remains a decision.

    201 when the observation is new, 200 when the same run attempt was already recorded.
    """
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        observation, created = record_deploy_observation(db, it, body)
    except DeployObservationRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    response.status_code = 201 if created else 200
    return _observation_dict(observation)


@router.get("/items/{item_id}/deploy-observations")
def list_deploy_observations(item_id: int, db: Session = Depends(get_db)) -> dict:
    """Every rollout observation on one change, plus the ONE that answers how it went.

    A separate route rather than a key on `_item_dict`, so the executor's list call carries no
    new payload and the watcher's read surface stays one path wide.

    `current` is served rather than left to the caller so the reduction over a contradicting
    append-only history has exactly one definition. A client that reduced it locally would be
    the second copy of a rule, which is the drift this estate has paid for four times over.
    `merge_commits_observed` carries more than one entry only when something recorded an
    observation about the wrong landing — reported, never refused.
    """
    if db.get(ChangeItem, item_id) is None:
        raise HTTPException(status_code=404, detail="not found")
    observations = observations_for(db, item_id)
    current = current_observation(observations)
    return {
        "item_id": item_id,
        "observations": [_observation_dict(ob) for ob in observations],
        "current": _observation_dict(current) if current is not None else None,
        "merge_commits_observed": merge_commits_observed(observations),
    }


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
    else:
        # A caller that does not name a pipeline gets the DERIVED ones. The 04:00
        # change-window executor lists approved items with no source filter and hands
        # what comes back to an LLM agent holding production Coolify tools; its own
        # filter is a denylist, so a source it predates arrives by default. Nothing is
        # authorized to execute a proposed change, so it is not offered.
        stmt = stmt.where(ChangeItem.source.notin_(sorted(PROPOSED_SOURCES)))
    if lane:
        stmt = stmt.where(ChangeItem.lane == lane)
    return [_item_dict(it) for it in db.scalars(stmt.order_by(ChangeItem.id)).all()]


@router.get("/items/{item_id}")
def get_item(item_id: int, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    return _item_dict(it)


@router.get("/events")
def list_events(
    after_id: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> dict:
    """Read-only event feed for the factory-events adapter (WS-1.1). Cursor = id."""
    rows = db.execute(
        select(ChangeEvent, ChangeItem)
        .join(ChangeItem, ChangeEvent.item_id == ChangeItem.id)
        .where(ChangeEvent.id > after_id)
        .order_by(ChangeEvent.id.asc())
        .limit(limit)
    ).all()
    return {
        "events": [
            {
                "id": ev.id,
                "item_id": ev.item_id,
                "at": ev.at.isoformat(),
                "actor": ev.actor,
                "event_type": ev.event_type,
                "from_status": ev.from_status,
                "to_status": ev.to_status,
                "detail": ev.detail,
                "attempt_id": ev.attempt_id,
                "window_run_id": ev.window_run_id,
                "item_identity": item.identity,
                "item_rule_key": item.rule_key,
                "item_instance": item.instance,
            }
            for ev, item in rows
        ]
    }


def _require_executor(it: ChangeItem) -> None:
    """Refuse every door into the EXECUTION lifecycle for a proposed change.

    The window executor makes THREE calls, not two — it lists, claims, and then posts
    an outcome (`run-window.ts` getApproved/claim/postOutcome, and `security-executor.ts`
    likewise). Guarding only `claim` leaves `outcome` reachable on an unclaimed item,
    which writes a `ChangeAttempt` and an `attempt_done` event asserting that an agent
    applied a deploy nothing performed — and that event ships to the tamper-evident
    factory-events chain. `outcome` is unreachable in practice only because the
    executor skips an item whose claim failed, and this repository has twice now
    written down that "unreachable because its only caller checks first" is not a
    property a future caller inherits.
    """
    if not it.has_authorized_executor:
        raise HTTPException(
            status_code=409,
            detail=f"'{it.source}' changes have no authorized executor (item {it.id})",
        )


# outcome → resulting item status + the event type to record
_OUTCOME_STATUS = {
    "done": ("done", "attempt_done"),
    "failed": ("failed", "attempt_failed"),
    "blocked": ("blocked", "attempt_blocked"),
    "skipped_conformant": ("resolved", "resolved"),
}


@router.post("/items/{item_id}/claim")
def claim(item_id: int, body: ClaimIn | None = None, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    _require_executor(it)
    if it.status != "approved":
        raise HTTPException(status_code=409, detail=f"not approved (status={it.status})")
    it.status = "in_progress"
    record_event(
        db,
        it,
        actor=body.actor if body else "executor",
        event_type="claimed",
        from_status="approved",
        to_status="in_progress",
    )
    db.commit()
    return _item_dict(it)


@router.post("/items/{item_id}/outcome")
def outcome(item_id: int, body: OutcomeIn, db: Session = Depends(get_db)) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    _require_executor(it)
    if body.outcome not in _OUTCOME_STATUS:
        raise HTTPException(status_code=422, detail=f"unknown outcome {body.outcome}")
    new_status, event_type = _OUTCOME_STATUS[body.outcome]
    now = datetime.now(UTC)
    attempt = ChangeAttempt(
        item_id=it.id,
        started_at=now,
        finished_at=now,
        outcome=body.outcome,
        detail=body.detail,
        tool_calls=body.tool_calls,
        rollback=body.rollback,
    )
    db.add(attempt)
    db.flush()
    prev = it.status
    it.status = new_status
    record_event(
        db,
        it,
        actor=body.actor,
        event_type=event_type,
        from_status=prev,
        to_status=new_status,
        detail=body.detail,
        attempt_id=attempt.id,
    )
    db.commit()
    return _item_dict(it)


def _decide(db: Session, item_id: int, body: DecisionIn, new_status: str, event_type: str) -> dict:
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    _do_decide(
        db, it, actor=body.actor, new_status=new_status, event_type=event_type, detail=body.detail
    )
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
    # A proposed item carries no handoff brief, so `handed_off` would park it in a
    # status no lane owns — and `revert_stale_handoffs` is forbidden from rescuing it.
    _require_executor(it)
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
        record_event(
            db, it, actor="api", event_type="pr_linked", detail=f"PR linked: {body.pr_url}"
        )
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
    return {
        "id": w.id,
        "status": w.status,
        "considered": w.considered,
        "applied": w.applied,
        "failed": w.failed,
        "blocked": w.blocked,
        "skipped": w.skipped,
    }


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
