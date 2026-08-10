import re
import unicodedata
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
