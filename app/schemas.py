from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _required_text(value: str, field: str) -> str:
    """Strip, and refuse blank. A field that may be an empty string is a field that
    will be — every text field a deploying change is REFUSED for lacking goes
    through here."""
    text = value.strip()
    if not text:
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

    target_repository: str  # "owner/repo"
    pull_request_number: int = Field(gt=0)
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
        owner, _, repo = text.partition("/")
        if not owner or not repo or "/" in repo or any(c.isspace() for c in text):
            raise ValueError("target_repository must be 'owner/repo'")
        return text

    @field_validator("change_class", "risk", "reasoning", "actor")
    @classmethod
    def _not_blank(cls, v: str, info) -> str:
        return _required_text(v, info.field_name)

    @field_validator("acceptance_criteria")
    @classmethod
    def _criteria_are_not_blank(cls, v: list[str]) -> list[str]:
        return [_required_text(c, "acceptance_criteria[]") for c in v]
