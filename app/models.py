from datetime import datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.sources import POLICY_APPROVED_SOURCES, PROPOSED_SOURCES, WORK_SOURCE


class ChangeItem(Base):
    __tablename__ = "change_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    identity: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    instance: Mapped[str] = mapped_column(String, nullable=False)
    rule_key: Mapped[str] = mapped_column(String, nullable=False)
    provider: Mapped[str | None] = mapped_column(String)
    resource_type: Mapped[str | None] = mapped_column(String)
    # Infrastructure-resource identifiers: a scan always has them, a proposal never
    # does. Required of every derived item by `EscalationIn`, which is the only
    # writer that can set them.
    resource_uuid: Mapped[str | None] = mapped_column(String)
    resource_name: Mapped[str | None] = mapped_column(String)
    risk: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    plan: Mapped[dict] = mapped_column(JSON, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, default="pending", index=True)
    # Pipeline source ("drift" = Coolify drift audit, "security" = machine security-scan).
    # Reconcile resolves stale items SCOPED to source so the two pipelines don't clobber
    # each other's queues.
    source: Mapped[str] = mapped_column(
        String, nullable=False, default="drift", server_default="drift", index=True
    )
    # Urgent lane: time-sensitive security findings surface first in the GUI.
    urgent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false", index=True
    )
    decided_by: Mapped[str | None] = mapped_column(String)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_report: Mapped[str | None] = mapped_column(String)
    handoff_brief: Mapped[str | None] = mapped_column(Text)
    handed_off_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lane: Mapped[str] = mapped_column(
        String, nullable=False, default="infra-config", server_default="infra-config", index=True
    )
    handoff: Mapped[dict | None] = mapped_column(JSON)
    pr_url: Mapped[str | None] = mapped_column(String)
    # ADR-0019: a deploying-merge change — an SDS-initiated merge into a repository
    # where landing on `main` IS deploying production. Set together by the proposal
    # route and by nothing else; null on every derived item.
    target_repository: Mapped[str | None] = mapped_column(String)
    pull_request_number: Mapped[int | None] = mapped_column(Integer)
    change_class: Mapped[str | None] = mapped_column(String)
    # What must hold after the deploy, and what to do when it does not. Distinct
    # columns rather than keys in `plan` so a deploying change can be REFUSED for
    # lacking them, which is the reason ADR-0019 records them at all.
    acceptance_criteria: Mapped[list | None] = mapped_column(JSON)
    rollback_plan: Mapped[dict | None] = mapped_column(JSON)
    # WHICH VERSION OF THE DEPLOY POLICY APPROVED THIS RECORD (ADR-0019 increment 5). Written by
    # the server, together with `status`, `decided_by` and `decided_at`, in one transaction and
    # from one place. Null on every derived item and on any deploy record that has not conformed.
    #
    # It is stored rather than recomputed, and that is the property adversarial review insisted
    # on: a subject must carry the revision it was decided under, or "which version permitted this,
    # and does it actually permit it?" has no answer once the policy has moved. It is what
    # `landing_ledger`'s rule pin already does for a landing, in the same estate, for the same
    # reason.
    policy_version: Mapped[int | None] = mapped_column(Integer)
    # ADR-0026: WHICH APPROVED INTENT PACKAGE EFFECTS THIS WORK. A work proposal names a
    # package the orchestrator can already intake; it does not describe the work in prose and
    # leave somebody to find one. The three together are a locator, and they are the whole
    # payload the carry needs -- every other field of a package intake is derived from the
    # package itself by `orchestrator emit-intake-payload`.
    #
    # DISTINCT COLUMNS RATHER THAN KEYS IN `plan`, for the reason ADR-0019 gives one screen up
    # about `acceptance_criteria` and `rollback_plan`: the proposal route refuses a record that
    # lacks them, and a refusal needs a column to be absent from. The infrastructure-shaped
    # columns above do not fit -- `resource_uuid`/`resource_name` identify a Coolify resource,
    # and `target_repository` is ADR-0019's deploying-merge subject, which this is not.
    # Null on every other source.
    package_id: Mapped[str | None] = mapped_column(String)
    package_revision: Mapped[int | None] = mapped_column(Integer)
    package_source_repository: Mapped[str | None] = mapped_column(String)

    @property
    def package_subject(self) -> tuple[str, int, str] | None:
        """The (package, revision, repository) this work proposal is about, or None.

        The triple rather than a boolean, for the reason `merge_subject` gives: one definition
        of "names a package", which callers narrow off, instead of a predicate asserting the
        fields are present and every caller re-checking that they are.

        Keyed on `WORK_SOURCE` and not on `PROPOSED_SOURCES`, which is the same care
        `names_a_merge` takes in the other direction: "proposed" and "names a package" coincide
        over no source but this one, and a future proposed source that has nothing to do with
        intent packages must not read as one that does.
        """
        if self.source != WORK_SOURCE:
            return None
        if self.package_id is None or self.package_revision is None:
            return None
        if self.package_source_repository is None:
            return None
        return self.package_id, self.package_revision, self.package_source_repository

    @property
    def has_authorized_executor(self) -> bool:
        """Whether anything in the estate is authorized to carry this change out.

        Derived items are executed by the change-window lanes. A proposed one is not:
        a deploying merge is landed by merging a pull request, which is increments 3
        and 4 of ADR-0019. Every door into the EXECUTION lifecycle asks this — claim,
        outcome and handoff — so "no authorized executor" is asserted at all of them
        rather than at whichever one was thought of first. The DECISION lifecycle
        (approve / defer / wontfix / resolve / reactivate) is unaffected.
        """
        return self.source not in PROPOSED_SOURCES

    @property
    def human_may_approve(self) -> bool:
        """Whether a human's Approve click is what moves this record forward.

        **NOT the complement of `has_authorized_executor`, though both templates rendered
        it as one, and that hid the only control a work proposal needs.** The two coincided
        while `deploy` was the sole proposed source: a deploying merge has no change-window
        executor AND is approved by policy, so "no executor" was a usable stand-in for "no
        human approval". A work proposal (ADR-0026) breaks the coincidence — it has no
        change-window executor either, and a human's approval is exactly what it waits for,
        which is why `POLICY_APPROVED_SOURCES` was split out of `PROPOSED_SOURCES`.

        The templates asked the executor question and got the wrong answer: on 2026-08-19
        Devon was offered only Resolve and Won't-fix on a record whose entire purpose was to
        be approved, and item 59 was retired by the only forward-looking button on the page.
        `transitions.decide` refuses approval for `POLICY_APPROVED_SOURCES` and nothing else,
        so this predicate mirrors the server rather than approximating it.
        """
        return self.source not in POLICY_APPROVED_SOURCES

    @property
    def merge_subject(self) -> tuple[str, int] | None:
        """The (repository, pull request) whose landing this change is about, or None.

        Returns the pair rather than a boolean so there is ONE definition of "names a merge"
        and callers narrow off it, instead of a predicate saying the fields are present and
        every caller re-checking that they are.
        """
        if self.source not in PROPOSED_SOURCES:
            return None
        if self.target_repository is None or self.pull_request_number is None:
            return None
        return self.target_repository, self.pull_request_number

    @property
    def names_a_merge(self) -> bool:
        """Whether this change identifies a pull request whose landing can be OBSERVED.

        Deliberately NOT the set-complement of `has_authorized_executor`, though it looks like
        one and a first draft was written that way. "Not executable by a change-window lane" and
        "names a merge" are different properties that happen to coincide over today's one
        proposed source, and keying on the first would admit a rollout observation against any
        FUTURE proposed source that has nothing to do with merging — failing closed only by way
        of a second guard, which is an accident rather than a design. So the predicate asserts
        the thing the observation actually needs: a repository and a pull request to attribute
        the rollout to.
        """
        return self.merge_subject is not None


class DeployObservation(Base):
    """What was observed about the rollout a deploying merge caused. APPEND-ONLY.

    Not an outcome. An outcome asserts that an authorized executor APPLIED a change, writes a
    `ChangeAttempt` and moves the item; increment 1 closed that door for proposed sources and
    it stays closed. This is a fact about the world, recorded by a watcher that acts on
    nothing: no `ChangeAttempt`, no transition. Terminating the record remains a decision.

    Every column below is a COORDINATE or a raw fact, except `verdict`, which the server
    derives from `run_conclusion`. The caller may not assert a verdict. The coordinates are
    the point: change-manager has no GitHub egress, so this row is asserted rather than
    observed by the server, and the only honest mitigation is that anyone can re-derive it
    from the primary source years later.
    """

    __tablename__ = "deploy_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("change_items.id"), nullable=False, index=True)
    # Server-built from (item, merge commit, run, attempt). Unique, so re-running the watcher
    # replays instead of appending a duplicate, and a genuinely new run attempt appends.
    observation_key: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    merge_commit_sha: Mapped[str] = mapped_column(String, nullable=False)
    # When GitHub said the pull request landed. REQUIRED, because GitHub populates
    # `merge_commit_sha` on OPEN pull requests with a throwaway test-merge commit that passes
    # every shape check there is — item 44's own subject, PR #42, has one right now. Demanding
    # the merge instant does not let this server verify the merge happened (it has no GitHub
    # egress), but it makes the assertion explicit and re-derivable instead of implied by a
    # field that is populated either way.
    merged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False, index=True)
    # The second axis: was production told anything at all? Derived, like the verdict.
    production_reached: Mapped[str] = mapped_column(String, nullable=False)
    workflow_path: Mapped[str] = mapped_column(String, nullable=False)
    # The blob sha of that workflow file AS IT WAS at the merge commit, and the transcribed
    # meaning of a green run at those bytes. Without them "the run concluded success" is three
    # different claims wearing one word.
    workflow_revision: Mapped[str | None] = mapped_column(String)
    workflow_attestation: Mapped[str] = mapped_column(String, nullable=False)
    # Which job and step the watcher looked at, and how each concluded. The names are stored as
    # well as the outcomes so the row says what question was asked, not only its answer.
    rollout_job: Mapped[str | None] = mapped_column(String)
    rollout_job_conclusion: Mapped[str | None] = mapped_column(String)
    trigger_step: Mapped[str | None] = mapped_column(String)
    trigger_step_conclusion: Mapped[str | None] = mapped_column(String)
    # Another rollout run of the same workflow that overlapped this one. Both repositories
    # redeploy a floating tag with no concurrency group, so an overlap means the two were racing
    # the same tag and a failure here may be a lost race rather than a broken build.
    concurrent_run_id: Mapped[int | None] = mapped_column(BigInteger)
    # BigInteger, deliberately: GitHub run ids passed 2^31 long ago (31426195637 is a real one
    # from this repository's own history), so Integer overflows on Postgres and silently does
    # not on SQLite — the shape of increment 1's int4 finding, one column over.
    run_id: Mapped[int | None] = mapped_column(BigInteger)
    run_attempt: Mapped[int | None] = mapped_column(Integer)
    run_url: Mapped[str | None] = mapped_column(String)
    run_conclusion: Mapped[str | None] = mapped_column(String)
    run_concluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_by: Mapped[str] = mapped_column(String, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ChangeAttempt(Base):
    __tablename__ = "change_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("change_items.id"), nullable=False)
    window_run_id: Mapped[int | None] = mapped_column(ForeignKey("window_runs.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[dict | None] = mapped_column(JSON)
    rollback: Mapped[dict | None] = mapped_column(JSON)


class ChangeEvent(Base):
    __tablename__ = "change_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("change_items.id"), nullable=False, index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String)
    to_status: Mapped[str | None] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(Text)
    attempt_id: Mapped[int | None] = mapped_column(ForeignKey("change_attempts.id"))
    window_run_id: Mapped[int | None] = mapped_column(ForeignKey("window_runs.id"))


class WindowRun(Base):
    __tablename__ = "window_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    considered: Mapped[int] = mapped_column(Integer, default=0)
    applied: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    blocked: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    report_md: Mapped[str | None] = mapped_column(Text)
