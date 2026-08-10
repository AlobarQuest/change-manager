"""Record what was observed about the rollout a deploying merge caused. ADR-0019 increment 2.

THE SERVER DERIVES THE VERDICT. The caller supplies facts and coordinates -- which merge, which
workflow run, how GitHub said it concluded -- and never a judgment. `verdict` is not an accepted
field, and the schema forbids extras, so sending one is a 422. Otherwise a watcher could report
`run_conclusion: "failure"` alongside `verdict: "success"` and the record would carry whichever
the caller preferred, which is the whole failure mode this estate keeps rediscovering under the
name "asserted, not observed".

THE VERDICT VOCABULARY IS infraops', PLUS ONE. `DeployVerdict` in
`infraops-mcp-server/src/change-manager/tools.ts` is `success | failed | pending | unknown`, and
its docstring carries the rule: `unknown` is inconclusive, "never a revert trigger on its own".
Taken as-is. `absent` is added, and the divergence is deliberate: `deploymentSucceeded` polls
seconds after its own write, where "no deployment found" honestly means "too early", so folding
it into `unknown` is right there. A watcher looks at a merge minutes-to-hours old, where the same
observation means the rollout NEVER RAN -- a finding, not the absence of one. `pending` is never
persisted: a verdict is a settled answer, and a row meaning "ask again" is not one.

NOTHING HERE ACTS, and nothing here transitions. An observation appends a row and a history
event. Whether the change is finished stays a decision -- a human's today, policy's in
increment 4.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.events import record_event
from app.identity import deploy_identity
from app.models import ChangeItem, DeployObservation
from app.schemas import DeployObservationIn

# The event appended to the change's history when a rollout is observed. A NEW type rather than a
# reused one: `attempt_done` asserts an executor applied something, which is exactly what did not
# happen here, and that event ships to the tamper-evident factory-events chain.
OBSERVED_EVENT = "deploy_observed"

VERDICT_SUCCESS = "success"
VERDICT_FAILED = "failed"
VERDICT_UNKNOWN = "unknown"
VERDICT_ABSENT = "absent"

VERDICTS = frozenset({VERDICT_SUCCESS, VERDICT_FAILED, VERDICT_UNKNOWN, VERDICT_ABSENT})

# Did production get told anything? A SECOND axis, and the verdict alone is not a substitute for
# it. Every rollout failure in either repository's history concluded `failure` at the run, and
# two of the three never reached production at all -- so acting on `failed` without this would,
# in those two cases, have made the rollback the only production mutation of the day.
REACHED_YES = "yes"
REACHED_NO = "no"
REACHED_UNKNOWN = "unknown"

PRODUCTION_REACHED = frozenset({REACHED_YES, REACHED_NO, REACHED_UNKNOWN})

# GitHub's documented `conclusion` values, bucketed. `cancelled` sits with the inconclusive ones
# rather than with the failures: a cancelled run says a human or a queue stopped it, not that
# production is broken, and inconclusive is the answer that licenses nothing.
_SUCCEEDED = frozenset({"success"})
_FAILED = frozenset({"failure", "timed_out", "startup_failure"})
_INCONCLUSIVE = frozenset({"cancelled", "skipped", "neutral", "action_required", "stale"})

CONCLUSIONS = _SUCCEEDED | _FAILED | _INCONCLUSIVE


class DeployObservationRefused(Exception):
    """The observation does not belong to this change, or contradicts one already recorded."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def verdict_for(conclusion: str | None, *, raced: bool = False) -> str:
    """Derive the verdict from what GitHub said. Never upgrades an unrecognised value.

    A conclusion this server does not know is `unknown`, not a refusal and certainly not a
    success: the raw string is stored verbatim alongside, so nothing is lost, and a value GitHub
    adds after this code was written degrades to "we do not know" rather than blocking the record
    or quietly reading as green.

    `raced` demotes a failure to inconclusive, and it is not a courtesy. Both repositories
    redeploy a FLOATING image tag (`:main`, `:latest`) and neither workflow declares a
    `concurrency` group, while change-manager's verify step waits ten minutes to see its own
    commit reported by production. So when a second merge lands mid-poll and its image wins, the
    first run polls to its deadline and exits 1 — a lost race, not a broken deployment, and
    rolling back on it would revert a build that is fine. Merges 108 and 131 seconds apart have
    already happened in this repository, before auto-merge; opening that lane is what makes
    back-to-back ordinary.
    """
    if conclusion is None:
        return VERDICT_ABSENT
    if conclusion in _SUCCEEDED:
        return VERDICT_SUCCESS
    if conclusion in _FAILED:
        return VERDICT_UNKNOWN if raced else VERDICT_FAILED
    return VERDICT_UNKNOWN


def production_reached_for(
    job_conclusion: str | None,
    step_conclusion: str | None,
    *,
    classified: bool,
    ran_at_all: bool = True,
) -> str:
    """Was production told anything? Positive evidence is required for the consequential answer.

    `no` is the value that says "do not roll back — nothing was deployed", so it is asserted only
    on positive evidence: no rollout run exists at all, or the rollout job is absent from a
    completed run, or it concluded `skipped`. `yes` requires the trigger step to have concluded
    `success`.

    Everything else is `unknown`, INCLUDING a failed trigger step — which for a single-target
    repository probably does mean nothing was told, and for `brain`, whose step is a loop over
    four webhooks under `bash -e`, means an unknown prefix of them was. Collapsing that into
    `no` would be the same overstatement as calling a liveness poll a revision check.
    """
    if not ran_at_all:
        # No run means nothing executed, so nothing was told. This is the clearest `no` there is
        # and it does not depend on anyone having classified the workflow — an earlier draft
        # gated it on classification and answered `unknown` for the one case that is certain.
        return REACHED_NO
    if not classified:
        # Nobody transcribed which job talks to production for these bytes, so the names the
        # caller looked at cannot be trusted to be the right ones.
        return REACHED_UNKNOWN
    if job_conclusion is None or job_conclusion == "skipped":
        return REACHED_NO
    if step_conclusion == "success":
        return REACHED_YES
    return REACHED_UNKNOWN


def observation_key(
    item_id: int, merge_commit_sha: str, run_id: int | None, attempt: int | None
) -> str:
    """The identity of one observation. Re-observing the same run attempt is a REPLAY.

    Keyed on the run attempt, not the run: a re-run supersedes its predecessor and concludes
    differently, and both are true things that happened.
    """
    if run_id is None:
        return f"{item_id}:{merge_commit_sha}:no-run"
    return f"{item_id}:{merge_commit_sha}:{run_id}:{attempt or 1}"


def _subject(item: ChangeItem, body: DeployObservationIn) -> None:
    """Refuse an observation that is not about THIS change.

    Increment 1's kill was that every guard keyed on `source` while the write joined on
    `identity`, and identity was as caller-derived as source. The lesson generalises rather than
    being about that one field: check what the write joins on. This write joins on `item_id`
    taken from the path, so the guard is that the FACTS the caller sends must agree with the row
    that id resolves to -- repository and pull request both, case-folded the same way the
    identity is, so a caller cannot record a verdict against a neighbouring change by naming the
    right item and the wrong merge.
    """
    subject = item.merge_subject
    if subject is None:
        raise DeployObservationRefused(
            f"'{item.source}' item {item.id} names no pull request, "
            f"so no rollout can be attributed to it"
        )
    claimed = deploy_identity(body.target_repository, body.pull_request_number)
    held = deploy_identity(*subject)
    if claimed != held:
        raise DeployObservationRefused(
            f"the observation names {claimed} and item {item.id} is {held}"
        )


def record_deploy_observation(
    db: Session, item: ChangeItem, body: DeployObservationIn
) -> tuple[DeployObservation, bool]:
    """Append one observation. Returns (row, created); a repeat of the same attempt replays.

    The item's STATUS is deliberately not checked. A rollout that failed must be recordable
    whatever the record says about itself -- refusing on status would put the hole exactly where
    the tool matters, and an observation is inert on a settled record in any case.
    """
    _subject(item, body)

    key = observation_key(item.id, body.merge_commit_sha, body.run_id, body.run_attempt)
    existing = db.execute(
        select(DeployObservation).where(DeployObservation.observation_key == key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    verdict = verdict_for(body.run_conclusion, raced=body.concurrent_run_id is not None)
    reached = production_reached_for(
        body.rollout_job_conclusion,
        body.trigger_step_conclusion,
        # An unclassified workflow revision means nobody said which job talks to production, so
        # whatever the caller looked at may be the wrong job entirely.
        classified=body.workflow_attestation != "unknown",
        ran_at_all=body.run_id is not None,
    )
    observation = DeployObservation(
        item_id=item.id,
        observation_key=key,
        merge_commit_sha=body.merge_commit_sha,
        merged_at=body.merged_at,
        verdict=verdict,
        production_reached=reached,
        workflow_path=body.workflow_path,
        workflow_revision=body.workflow_revision,
        workflow_attestation=body.workflow_attestation,
        rollout_job=body.rollout_job,
        rollout_job_conclusion=body.rollout_job_conclusion,
        trigger_step=body.trigger_step,
        trigger_step_conclusion=body.trigger_step_conclusion,
        concurrent_run_id=body.concurrent_run_id,
        run_id=body.run_id,
        run_attempt=body.run_attempt,
        run_url=body.run_url,
        run_conclusion=body.run_conclusion,
        run_concluded_at=body.run_concluded_at,
        observed_at=body.observed_at,
        observed_by=body.actor,
        recorded_at=datetime.now(UTC),
    )
    db.add(observation)
    record_event(
        db,
        item,
        actor=body.actor,
        event_type=OBSERVED_EVENT,
        # No from_status/to_status: observing a rollout moves nothing, and writing the current
        # status into both would make the history read like a transition that did not happen.
        # Written to be self-contained on purpose. `change_events` is not dropped by this
        # migration's downgrade and the observation table is, so this line is what survives a
        # rollback of the image — it has to carry the whole finding, not a pointer to it.
        detail=(
            f"rollout observed for {item.target_repository}#{item.pull_request_number} "
            f"at merge commit {body.merge_commit_sha}: verdict={verdict}, "
            f"production_reached={reached}"
            + (
                f", run {body.run_id} attempt {body.run_attempt} concluded "
                f"{body.run_conclusion} ({body.run_url})"
                if body.run_id is not None
                else ", no run was found at that commit"
            )
            + f"; a green run of {body.workflow_path} at revision "
            f"{body.workflow_revision or 'unknown'} attests {body.workflow_attestation}"
        ),
    )
    try:
        db.commit()
    except IntegrityError:
        # Two watchers observed the same attempt at once. The loser replays the winner's row,
        # which is what a repeat of this call is supposed to do.
        db.rollback()
        winner = db.execute(
            select(DeployObservation).where(DeployObservation.observation_key == key)
        ).scalar_one_or_none()
        if winner is None:
            raise
        return winner, False
    return observation, True


def observations_for(db: Session, item_id: int) -> list[DeployObservation]:
    """Every observation on a change, oldest first. Append-only, so this is the whole history."""
    return list(
        db.execute(
            select(DeployObservation)
            .where(DeployObservation.item_id == item_id)
            .order_by(DeployObservation.id)
        ).scalars()
    )


def current_observation(observations: list[DeployObservation]) -> DeployObservation | None:
    """Reduce an append-only history to the ONE row that answers "how did the rollout go?".

    A change legitimately accumulates contradicting settled verdicts and this is not a defect:
    `absent` at 09:00 because GitHub had not indexed the run yet, `success` at 09:30 once it
    had; `unknown` for a cancelled first attempt, `success` for the re-run. Append-only keeps
    both, because both happened. But every reader -- the detail page, the watcher, increment 4's
    policy -- needs one answer, and if the rule is not stated here each of them invents its own.

    The rule, in order: an observation that SAW A RUN beats one that saw none, because "no run
    exists yet" is only ever evidence about the moment it was taken; among those, the highest
    (run id, attempt), because a re-run supersedes what it re-ran; and failing all that, the
    latest row appended.
    """
    if not observations:
        return None
    with_runs = [ob for ob in observations if ob.run_id is not None]
    if with_runs:
        return max(with_runs, key=lambda ob: (ob.run_id or 0, ob.run_attempt or 0, ob.id))
    return max(observations, key=lambda ob: ob.id)


def merge_commits_observed(observations: list[DeployObservation]) -> list[str]:
    """The distinct merge commits a change has been observed at, in first-seen order.

    More than one is a DIVERGENCE and a finding for whoever is looking -- a pull request merges
    once, so two commits means something recorded an observation about the wrong landing. It is
    reported and never refused: `merge_commit_sha` is caller-supplied and change-manager has no
    GitHub egress with which to check it, and GitHub populates that field on OPEN pull requests
    with a throwaway test-merge commit that passes every shape check there is. A server that
    refused the second value would freeze whichever arrived first -- and with no supersession,
    no delete route and `PATCH` limited to `pr_url`, a single wrong POST would make the true
    verdict unrecordable against that change forever. Reporting a divergence costs a finding;
    refusing one costs the record.
    """
    seen: list[str] = []
    for ob in observations:
        if ob.merge_commit_sha not in seen:
            seen.append(ob.merge_commit_sha)
    return seen
