from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


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
