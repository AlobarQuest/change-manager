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
)
from app.deploy_policy import current as current_policy
from app.deploy_policy import landing_conditions_dict, objections, policy_dict
from app.deploy_retirement import RetirementRefused, retire_deploy_change
from app.deploy_settlement import record_rollout_and_settle
from app.events import record_event
from app.guards import require_executor, require_policy_approver
from app.models import ChangeAttempt, ChangeEvent, ChangeItem, DeployObservation, WindowRun
from app.reconcile import reconcile
from app.schemas import (
    ClaimIn,
    DecisionIn,
    DeployChangeIn,
    DeployObservationIn,
    DeployRetirementIn,
    OutcomeIn,
    SyncRequest,
    SyncSummary,
    WorkChangeIn,
    WorkRetirementIn,
)
from app.sources import POLICY_APPROVED_SOURCES, PROPOSED_SOURCES, ProposedSourceError
from app.transitions import TransitionError
from app.transitions import decide as _do_decide
from app.transitions import hand_off as _do_hand_off
from app.transitions import reactivate as _do_reactivate
from app.work_changes import (
    WorkChangeConflict,
    WorkChangeIdentityHeld,
    propose_work_change,
)
from app.work_retirement import WorkRetirementRefused, retire_work_change

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
        # Which pinned policy version approved this record. STORED, so an approval stays
        # re-derivable after the policy has moved on.
        "policy_version": it.policy_version,
        # Why it does not currently conform, recomputed here. This is EXPLANATORY and never
        # permissive: `status` is the stored decision, and nothing downstream may read this
        # list as an approval. It exists so an operator looking at a pending record can see
        # what a human would have to ratify, instead of diffing two artifacts by hand.
        # Keyed on `POLICY_APPROVED_SOURCES`, so this is projected onto the records the deploy
        # policy actually governs. On any other proposed source (ADR-0026's work proposals)
        # `objections` would answer `target_repository_unreadable` -- a record failing to conform
        # to a policy that was never about it, which is the estate's "not applicable is not the
        # same answer as not met" four times over.
        "policy_objections": list(objections(current_policy(), it))
        if it.source in POLICY_APPROVED_SOURCES
        else [],
        # ADR-0026. The package revision this work is about, carried on the record so the carry
        # reads a locator rather than parsing one out of `identity`. Null on every other source,
        # which is what `package_subject` asserts and what the carry refuses on.
        "package_id": it.package_id,
        "package_revision": it.package_revision,
        "package_source_repository": it.package_source_repository,
        # ADR-0019 increment 5b. What the CURRENT policy requires of the act, carried beside the
        # record the act would be about. `GET /api/deploy-policy` serves the same thing standing
        # alone and is the surface a person reads; this is the surface the landing party reads,
        # and it is here rather than there for two reasons.
        #
        # The first is decisive and was measured rather than predicted: the orchestrator's
        # architecture guards forbid the bare token this service's policy route is spelled with,
        # anywhere under its source tree, and its own rule is to reword rather than to widen a
        # guard. It cannot name that path. It already reads this listing.
        #
        # The second is that the record and the conditions then arrive in ONE response, so they
        # cannot disagree across two calls -- the version a record was approved under and the
        # version now in force are compared from a single read of a single service.
        #
        # It is still one holder and one reader: this is a projection of the same artifact, not a
        # copy of it. `landing_policy_version` is the CURRENT version and is deliberately not the
        # same field as `policy_version` above, which is the version that approved this record.
        "landing_policy_version": current_policy().version,
        "landing_conditions": landing_conditions_dict(current_policy())
        if it.source in POLICY_APPROVED_SOURCES
        else None,
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


@router.post("/work-changes", status_code=201)
def propose_work(body: WorkChangeIn, response: Response, db: Session = Depends(get_db)) -> dict:
    """Propose work for the software delivery system to carry out (ADR-0026).

    201 when the record is created, 200 when an identical proposal already existed, 409 when a
    different one did or when the identity is held by another pipeline.

    The record is created `pending`. A human approves it here -- this route cannot, and neither
    can any other caller: approval is the ordinary decision, and it is the whole reason `work`
    is outside `POLICY_APPROVED_SOURCES`. Nothing in the change-window lanes will ever execute
    it; the carry (orchestrator `work-carrier`) reads the approved record and prepares an
    intake for it.
    """
    try:
        item, created = propose_work_change(db, body)
    except (WorkChangeConflict, WorkChangeIdentityHeld) as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    response.status_code = 201 if created else 200
    return _item_dict(item)


@router.post("/items/{item_id}/deploy-retirement")
def retire_deploy(item_id: int, body: DeployRetirementIn, db: Session = Depends(get_db)) -> dict:
    """Retire a deploying-merge record whose pull request was closed without merging.

    THE CALLER SUPPLIES A FACT, NOT A STATUS. That is what makes this reachable by the narrow
    `propose` credential when every other status-moving verb is the full credential's alone --
    and it is safe on a fact this service cannot check because the route can only ever REMOVE
    permission, never grant it. `app/deploy_retirement.py` carries the argument.

    Idempotent: a record already terminal answers 200 unchanged, because the producer sweeps on
    every pass and a retirement it already made must not become a finding.
    """
    item = db.get(ChangeItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    try:
        retire_deploy_change(
            db,
            item,
            observation=body.observation,
            pull_request_number=body.pull_request_number,
            actor=body.actor,
        )
    except RetirementRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _item_dict(item)


@router.post("/items/{item_id}/work-retirement")
def retire_work(item_id: int, body: WorkRetirementIn, db: Session = Depends(get_db)) -> dict:
    """Retire a work record whose work the software delivery system has built (ADR-0029).

    THE CALLER SUPPLIES A FACT, NOT A STATUS -- the same property that makes the deploying-merge
    retirement reachable by the narrow `propose` credential. It is safe on a fact this service
    cannot check because the route can only ever REMOVE permission, never grant it, and this
    service cannot check it at all: it has no orchestrator egress and never will.
    `app/work_retirement.py` carries the argument.

    Idempotent: a record already terminal answers 200 unchanged, because the producer sweeps on
    every pass and a retirement it already made must not become a finding.
    """
    item = db.get(ChangeItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    try:
        retire_work_change(
            db,
            item,
            observation=body.observation,
            package_id=body.package_id,
            package_revision=body.package_revision,
            actor=body.actor,
        )
    except WorkRetirementRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
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
    """Record what a watcher saw of the rollout this merge caused, and settle the record if that
    rollout confirmed the change landed (ADR-0019 increment 2; ADR-0022).

    NOT an outcome, and still not on the execution lifecycle: it writes no `ChangeAttempt`.
    Increment 1 closed `claim`/`outcome`/`handoff` to proposed sources — the doors that let
    something assert it had APPLIED a change — and this route does not reopen them, because
    observing is not applying.

    **IT CAN NOW MOVE A STATUS, and the caller still cannot choose one.** ADR-0022 gives the
    watcher the outcome: a record whose landing production confirmed is settled to `resolved`, by
    the verdict THIS SERVER DERIVED from the coordinates supplied. `verdict` is not an accepted
    field, the only reachable status is `resolved`, and no landing term accepts it — so this can
    remove permission and can never grant it. `app/deploy_settlement.py` carries the argument.

    201 when the observation is new, 200 when the same run attempt was already recorded. The
    settlement runs either way, because it is a function of the whole observed history rather than
    of this call — and the record that forced ADR-0022 already has its observation, so a REPLAY is
    the only route by which it can ever settle.
    """
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    try:
        observation, created, _settled = record_rollout_and_settle(db, it, body)
    except DeployObservationRefused as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    response.status_code = 201 if created else 200
    # `item_status` is the caller's only way to learn that its observation settled the record, and
    # it is on this route alone: the listing serves observations, which are facts about a rollout
    # and say nothing about the record's lifecycle. The watcher reports it, and it is what makes a
    # record that is terminal while its current observation is not a success visible to anybody.
    return _observation_dict(observation) | {"item_status": it.status}


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


@router.get("/landing-policy")
def landing_policy() -> dict:
    """The same document `GET /api/deploy-policy` serves, at a path the reader can NAME.

    ADR-0038. This is a second projection of one holder, never a second holder: same `current()`,
    same `policy_dict`, and a test asserts the two responses are equal. It exists because the party
    that lands cannot spell the other path -- its architecture guards forbid the bare token that
    path is spelled with anywhere under its source tree, measured with those guards' own tokenizers,
    which split on every non-alphanumeric character. Its own standing rule is to reword rather than
    to widen a guard, and a URL cannot be reworded.

    Until now that cost nothing: the conditions on the act are also projected onto each record in
    the item listing, whose path the reader can spell, and it read them there. ADR-0038's lane has
    no record to hang them on -- a repository where landing changes nothing already serving has no
    such record by construction -- so the block naming that population is reachable only by naming a
    path.

    THE OTHER ROUTE IS LEFT EXACTLY AS IT IS, and this is strictly additive. Devon deferred the
    rename on 2026-08-31: add the block, keep the name, rename later if the name starts misleading
    people. At that rename this path becomes the primary one and the other retires, which is why
    additive is the right shape now rather than a compromise.

    Read-scoped on the same terms as its twin: standing policy, no secret, and a caller that could
    not read it could only fail closed.
    """
    return policy_dict(current_policy())


@router.get("/deploy-policy")
def deploy_policy() -> dict:
    """What a human has pre-approved for a deploying merge, and the conditions on the act.

    THIS ROUTE EXISTS SO NOBODY HOLDS A SECOND COPY. The conditions under `landing` are
    about the CHANGE and about the moment -- the update type, whether the checks a landing
    rests on ran against the current base -- and this service can evaluate neither: it has
    no GitHub egress and cannot attest a caller, so a term here over caller-declared facts
    would be policy resting on something it cannot check. They are declared here, where a
    human edits them and where they are versioned, and evaluated by the party that can read
    GitHub, at the moment of the act.

    ADR-0019 increment 3 settled the same question in the other direction and its answer is
    the shape being followed: one holder, the only readable form is what the running process
    serves, and nobody keeps a copy.

    ADR-0038 gave it a TWIN at `/api/landing-policy`, serving this same document through the
    same builder, because the party that lands cannot spell this path -- its own architecture
    guards forbid the bare token this one is spelled with. Two projections of one holder, and a
    test asserts they agree. This path is unchanged and is still the one a person reads.

    Read-scoped: it is a statement of standing policy, carries no secret, and a caller that
    could not read it could only fail closed.
    """
    return policy_dict(current_policy())


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
    require_executor(it)
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
    require_executor(it)
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
    it = db.get(ChangeItem, item_id)
    if it is None:
        raise HTTPException(status_code=404, detail="not found")
    # Guarded HERE and in `transitions.decide`, and the second one is the load-bearing one.
    # This repository's increment-1 kill was a guard keyed on the right concept and the
    # wrong field, and the lesson generalises: the route is the readable refusal, the write
    # path is the guarantee. Every other caller of `decide` -- the four other verbs, the
    # GUI -- reaches the same check without needing to remember it.
    require_policy_approver(it)
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
    require_executor(it)
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
