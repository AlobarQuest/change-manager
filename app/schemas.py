import re
import unicodedata
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Unicode categories that carry no visible content: format characters (Cf — zero-width
# space, BOM, soft hyphen, the bidi marks), the space and line/paragraph separators,
# and control characters.
_INVISIBLE = {"Cf", "Zs", "Zl", "Zp", "Cc"}

# GitHub's own owner/repo grammar, matched rather than approximated. A shape check
# ("contains one slash, no whitespace") admits `../..`, `a/b?x=1`, `a/b#frag` and a
# name with a zero-width character in it — and increments 3 and 4 build GitHub API
# calls and the record's identity out of this string.
_REPOSITORY = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}")


def _required_text(value: str, field: str) -> str:
    """Strip, and refuse a value with nothing visible in it.

    A field that may be an empty string is a field that will be — and `str.strip()`
    alone does not deliver that, because it removes only `str.isspace()` characters.
    "​", a BOM, a soft hyphen and the Hangul filler all survive it and render as
    an empty bullet. Every text field a deploying change is REFUSED for lacking goes
    through here, so the refusal has to mean "carries something a human can read".
    """
    text = value.strip()
    if not any(unicodedata.category(c) not in _INVISIBLE for c in text):
        raise ValueError(f"{field} must not be blank")
    return text


class TargetIn(BaseModel):
    provider: str | None = None
    resource_type: str | None = None
    uuid: str
    name: str


class EscalationIn(BaseModel):
    proposal_id: str
    instance: str
    target: TargetIn
    risk: str
    kind: str
    reasoning: str
    plan: dict[str, Any]
    note: str | None = None
    urgent: bool = False
    # "infra-config" | "app-conformance"; default keeps legacy payloads valid
    lane: str = "infra-config"
    handoff_brief: str | None = None  # markdown build brief; present only for app-conformance
    handoff: dict[str, Any] | None = None  # structured handoff package (single source of truth)


class SyncRequest(BaseModel):
    generated_at: str
    source_report: str
    escalations: list[EscalationIn]
    # Pipeline source for this batch; reconcile scopes its "resolve absent items" pass
    # to this source. Defaults to "drift" for the existing Coolify pipeline.
    source: str = "drift"


class SyncSummary(BaseModel):
    new: int
    refreshed: int
    resolved: int
    reopened: int


class ClaimIn(BaseModel):
    actor: str = "executor"  # WS-1.2: executors declare a registry identity


class OutcomeIn(BaseModel):
    outcome: str  # done | failed | blocked | skipped_conformant
    detail: str | None = None
    tool_calls: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None
    actor: str = "executor"  # WS-1.2: executors declare a registry identity


class DecisionIn(BaseModel):
    actor: str  # the SSO email; for M2M/testing, an explicit actor
    detail: str | None = None


class RollbackPlanIn(BaseModel):
    """What to do when the acceptance criteria are not met.

    `steps` is the refusable core; extra keys are allowed so a proposer can carry the
    specifics of its own rollback (an image tag, a revert commit) without this schema
    having to anticipate them.
    """

    model_config = ConfigDict(extra="allow")

    steps: list[str] = Field(min_length=1)

    @field_validator("steps")
    @classmethod
    def _steps_are_not_blank(cls, v: list[str]) -> list[str]:
        return [_required_text(s, "rollback_plan.steps[]") for s in v]


class DeployChangeIn(BaseModel):
    """A proposed deploying-merge change (ADR-0019).

    Every value is SUPPLIED by the proposer. change-manager is the registrar, not the
    investigator: it does not read the target's deploy workflow or ask Coolify what a
    merge would do, because a registrar that infers what it is told cannot later be
    checked against the thing that told it.
    """

    # Nothing extra is accepted. `plan` and `handoff` are not inputs to this route, and
    # a caller that believes it is setting one should learn so rather than have it
    # dropped; the same goes for a mistyped `note`. The nested rollback plan opts the
    # other way on purpose — see RollbackPlanIn.
    model_config = ConfigDict(extra="forbid")

    target_repository: str  # "owner/repo"
    # strict: pydantic's lax mode reads `true` as 1, filing the change against pull
    # request #1 — and if a #1 record exists, replaying onto it and answering "already
    # recorded". The ceiling is int4's, because `pull_request_number` is an Integer
    # column: a larger value is accepted by SQLite and fails only on production
    # Postgres, which is the half of the estate the test suite cannot see.
    pull_request_number: int = Field(gt=0, le=2_147_483_647, strict=True)
    change_class: str
    risk: str
    reasoning: str
    acceptance_criteria: list[str] = Field(min_length=1)
    rollback_plan: RollbackPlanIn
    actor: str  # caller-declared; see the attribution note in the ADR-0019 plan
    note: str | None = None

    @field_validator("target_repository")
    @classmethod
    def _owner_slash_repo(cls, v: str) -> str:
        text = _required_text(v, "target_repository")
        if not _REPOSITORY.fullmatch(text):
            raise ValueError("target_repository must be a GitHub 'owner/repo' name")
        return text

    @field_validator("change_class", "risk", "reasoning", "actor")
    @classmethod
    def _not_blank(cls, v: str, info) -> str:
        return _required_text(v, info.field_name)

    @field_validator("acceptance_criteria")
    @classmethod
    def _criteria_are_not_blank(cls, v: list[str]) -> list[str]:
        return [_required_text(c, "acceptance_criteria[]") for c in v]


class WorkChangeIn(BaseModel):
    """A proposed piece of work for the software delivery system to carry out (ADR-0026).

    The record is the DECISION; the orchestrator holds everything after approval. What makes
    it carryable is that it names an approved intent package rather than describing work in
    prose: every other field of an orchestrator package intake is derived from the package
    itself, so a locator plus a human approval is the whole of what has to cross.

    change-manager is the registrar here exactly as it is for a deploying merge. It does not
    read the package, does not ask the orchestrator whether it exists, and cannot -- it has no
    egress. The carry verifies the locator against the real checkout before it prepares
    anything, and refuses rather than guessing; a registrar that inferred what it was told
    could not later be checked against the thing that told it.
    """

    # Nothing extra is accepted, for `DeployChangeIn`'s reason: a caller that believes it is
    # setting `plan`, or that mistyped `note`, should learn so rather than have it dropped.
    model_config = ConfigDict(extra="forbid")

    package_id: str
    # strict, and bounded by int4 because `package_revision` is an Integer column: pydantic's
    # lax mode reads `true` as 1, filing the proposal against revision 1 of the package -- and
    # if a revision-1 record exists, replaying onto it and answering "already recorded". The
    # ceiling is the one SQLite accepts and production Postgres refuses, which is the half of
    # the estate the test suite cannot see.
    package_revision: int = Field(gt=0, le=2_147_483_647, strict=True)
    package_source_repository: str  # "owner/repo" -- where the package is authored
    risk: str
    reasoning: str
    actor: str  # caller-declared; see the attribution note in the ADR-0019 plan
    note: str | None = None

    @field_validator("package_source_repository")
    @classmethod
    def _owner_slash_repo(cls, v: str) -> str:
        text = _required_text(v, "package_source_repository")
        if not _REPOSITORY.fullmatch(text):
            raise ValueError("package_source_repository must be a GitHub 'owner/repo' name")
        return text

    @field_validator("package_id", "risk", "reasoning", "actor")
    @classmethod
    def _not_blank(cls, v: str, info) -> str:
        return _required_text(v, info.field_name)


class DeployRetirementIn(BaseModel):
    """An observed fact about a deploying-merge record's subject (ADR-0019 increment 5b).

    There is NO status field, and that absence is the route's whole justification: the caller
    reports what it saw and the server decides what follows. Every other status-moving route in
    this service takes the new status from the caller, which is why they are the full
    credential's alone.

    The pull request number is repeated from the record rather than taken on trust from the path,
    for increment 1's reason: naming the subject twice is what lets the server refuse a mismatch
    instead of retiring whichever record the id happened to select.
    """

    model_config = ConfigDict(extra="forbid")

    observation: str
    pull_request_number: int = Field(gt=0, le=2_147_483_647, strict=True)
    actor: str

    @field_validator("observation", "actor")
    @classmethod
    def _not_blank(cls, v: str, info) -> str:
        return _required_text(v, info.field_name)


# A git object name as GitHub serves it. Anchored and lower-case: `fullmatch` on a case-folded
# value, so `ABC…`/`abc…` cannot become two spellings of one commit in the frozen-merge guard.
_OBJECT_NAME = re.compile(r"[0-9a-f]{40}")

# What a green run at the observed workflow revision actually attests. A closed vocabulary,
# because the watcher's registry is the only thing that knows the answer and a free string here
# would let an unclassified revision arrive wearing a strong word.
# Two rungs and an unknown, deliberately not three. A first draft had `liveness_confirmed`
# between "the webhook answered" and "the merged build is serving"; measurement removed it —
# Coolify's swap is a rolling update taking 43-73s while brain's job polls 30s in and breaks on
# the first 2xx, so the container that answered was the one already running. What each workflow
# revision actually checked is transcribed in the watcher's registry, where a difference that
# carries no guarantee belongs; the level a consumer keys on must not overstate.
ATTESTATIONS = ("revision_confirmed", "rollout_unverified", "unknown")


class DeployObservationIn(BaseModel):
    """What a watcher saw of the rollout a deploying merge caused (ADR-0019 increment 2).

    FACTS AND COORDINATES ONLY. There is no `verdict` field and extras are forbidden, so a
    caller cannot both report `run_conclusion: "failure"` and assert the rollout succeeded — the
    server derives the verdict from the conclusion. The coordinates exist so the row can be
    re-derived from GitHub by anyone, later: change-manager has no GitHub egress, so this record
    is asserted rather than observed here, and being re-checkable is the only honest mitigation
    available short of per-caller identity.
    """

    model_config = ConfigDict(extra="forbid")

    # Repeated from the item rather than taken on trust from the path, and checked against it.
    # Increment 1's kill was a guard keyed on one caller-derived field while the write joined on
    # another; naming the subject twice is what lets the server refuse a mismatch instead of
    # believing whichever field it happened to read.
    target_repository: str
    pull_request_number: int = Field(gt=0, le=2_147_483_647, strict=True)

    merge_commit_sha: str
    # REQUIRED. GitHub populates `merge_commit_sha` on OPEN pull requests with a throwaway
    # test-merge commit — a real, fetchable object that passes every shape check — so a shape
    # check on the sha does not establish that anything merged. Item 44's own subject, PR #42,
    # carries one today. Demanding the merge instant does not let this server verify the merge
    # (it has no GitHub egress), but it turns an omission into an explicit assertion.
    merged_at: datetime

    workflow_path: str
    workflow_revision: str | None = None
    workflow_attestation: str

    # The rollout job and its trigger step, by name and by conclusion.
    rollout_job: str | None = None
    rollout_job_conclusion: str | None = None
    trigger_step: str | None = None
    trigger_step_conclusion: str | None = None
    concurrent_run_id: int | None = Field(
        default=None, gt=0, le=9_223_372_036_854_775_807, strict=True
    )

    # A GitHub run id passed 2^31 long ago, so the ceiling here is int8's and the column is
    # BigInteger. int4 would be accepted by SQLite and fail only on production Postgres.
    run_id: int | None = Field(default=None, gt=0, le=9_223_372_036_854_775_807, strict=True)
    run_attempt: int | None = Field(default=None, gt=0, le=2_147_483_647, strict=True)
    run_url: str | None = None
    run_conclusion: str | None = None
    run_concluded_at: datetime | None = None

    observed_at: datetime
    actor: str  # caller-declared; see the attribution note in the ADR-0019 plan

    @field_validator("target_repository")
    @classmethod
    def _observed_owner_slash_repo(cls, v: str) -> str:
        text = _required_text(v, "target_repository")
        if not _REPOSITORY.fullmatch(text):
            raise ValueError("target_repository must be a GitHub 'owner/repo' name")
        return text

    @field_validator("merge_commit_sha")
    @classmethod
    def _merge_commit_is_an_object_name(cls, v: str) -> str:
        text = _required_text(v, "merge_commit_sha").lower()
        if not _OBJECT_NAME.fullmatch(text):
            raise ValueError("merge_commit_sha must be a 40-character git object name")
        return text

    @field_validator("workflow_revision")
    @classmethod
    def _revision_is_an_object_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        text = _required_text(v, "workflow_revision").lower()
        if not _OBJECT_NAME.fullmatch(text):
            raise ValueError("workflow_revision must be a 40-character git object name")
        return text

    @field_validator("workflow_attestation")
    @classmethod
    def _attestation_is_known(cls, v: str) -> str:
        text = _required_text(v, "workflow_attestation")
        if text not in ATTESTATIONS:
            raise ValueError(f"workflow_attestation must be one of {', '.join(ATTESTATIONS)}")
        return text

    @field_validator("workflow_path", "actor")
    @classmethod
    def _observation_text_is_not_blank(cls, v: str, info) -> str:
        return _required_text(v, info.field_name)

    @field_validator("rollout_job", "trigger_step")
    @classmethod
    def _optional_names_are_not_blank(cls, v: str | None, info) -> str | None:
        return None if v is None else _required_text(v, info.field_name)

    @field_validator("rollout_job_conclusion", "trigger_step_conclusion")
    @classmethod
    def _job_conclusions_are_tokens(cls, v: str | None, info) -> str | None:
        if v is None:
            return None
        text = _required_text(v, info.field_name)
        if len(text) > 64 or not re.fullmatch(r"[a-z_]+", text):
            raise ValueError(f"{info.field_name} must be a short lower-case conclusion token")
        return text

    @field_validator("observed_at", "merged_at")
    @classmethod
    def _required_instants_carry_an_offset(cls, v: datetime, info) -> datetime:
        if v.tzinfo is None:
            raise ValueError(f"{info.field_name} must carry a timezone offset")
        return v

    @field_validator("run_conclusion")
    @classmethod
    def _conclusion_is_a_token(cls, v: str | None) -> str | None:
        """Bounded, but NOT a closed vocabulary.

        GitHub may add a conclusion after this code was written. Refusing it would lose the
        record entirely, so the raw string is stored verbatim and the derived verdict degrades
        to `unknown` — which is inconclusive, and inconclusive licenses nothing.
        """
        if v is None:
            return None
        text = _required_text(v, "run_conclusion")
        if len(text) > 64 or not re.fullmatch(r"[a-z_]+", text):
            raise ValueError("run_conclusion must be a short lower-case GitHub conclusion token")
        return text

    @field_validator("run_concluded_at")
    @classmethod
    def _optional_instant_carries_an_offset(cls, v: datetime | None) -> datetime | None:
        """A naive datetime here becomes a TypeError deep in a comparison, which is a bare 500.

        Only handled exception types reach a clean response; everything else surfaces unhandled.
        So the offset is required at the edge, where it is a 422.
        """
        if v is not None and v.tzinfo is None:
            raise ValueError("run_concluded_at must carry a timezone offset")
        return v

    @model_validator(mode="after")
    def _the_run_is_present_or_absent_as_a_whole(self) -> "DeployObservationIn":
        """A run is observed completely or not at all, and only once it has SETTLED.

        Two shapes are admissible and nothing between them: a concluded run (id, attempt and
        conclusion all present), or no run at all (all three absent — the rollout never ran).
        A run id with no conclusion is a run still going, which is not a verdict; recording it
        would put a row meaning "ask again" into an append-only table.
        """
        has_run = self.run_id is not None
        if has_run and (self.run_attempt is None or self.run_conclusion is None):
            raise ValueError(
                "an observed run must carry run_attempt and run_conclusion: "
                "a run that has not concluded is not a verdict"
            )
        if not has_run and (
            self.run_attempt is not None
            or self.run_conclusion is not None
            or self.run_url is not None
            or self.run_concluded_at is not None
            or self.rollout_job_conclusion is not None
            or self.trigger_step_conclusion is not None
            or self.concurrent_run_id is not None
        ):
            raise ValueError("without run_id there is no run, so no run detail may be sent")
        return self
