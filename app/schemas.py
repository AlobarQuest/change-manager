from typing import Any

from pydantic import BaseModel


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


class SyncRequest(BaseModel):
    generated_at: str
    source_report: str
    escalations: list[EscalationIn]


class SyncSummary(BaseModel):
    new: int
    refreshed: int
    resolved: int
    reopened: int


class OutcomeIn(BaseModel):
    outcome: str  # done | failed | blocked | skipped_conformant
    detail: str | None = None
    tool_calls: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None


class DecisionIn(BaseModel):
    actor: str  # the SSO email; for M2M/testing, an explicit actor
    detail: str | None = None
