"""A deploying-merge change must survive every sweep that assumes drift shape.

`reconcile` resolves items ABSENT from a batch — that is what "the drift cleared"
means. A proposed change is absent from every scan there will ever be, so an
unguarded sweep marks it resolved on its next run, by a pipeline that has no idea it
exists. These are the tests that say it does not.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.deploy_changes import propose_deploy_change
from app.models import ChangeEvent, ChangeItem
from app.reconcile import reconcile
from app.schemas import DeployChangeIn, EscalationIn, SyncRequest, TargetIn
from app.sources import ProposedSourceError
from app.watchdog import revert_stale_handoffs


def sync_req(escalations, source):
    return SyncRequest(
        generated_at="2026-08-10T03:00:00Z",
        source_report=f"2026-08-10.{source}.json",
        escalations=escalations,
        source=source,
    )


def an_escalation(uuid="db1"):
    return EscalationIn(
        proposal_id="572:rand",
        instance="prod",
        target=TargetIn(provider="coolify", resource_type="database", uuid=uuid, name="pg1"),
        risk="safe",
        kind="question",
        reasoning="rule #572",
        plan={"root_cause": "x"},
    )


@pytest.mark.parametrize("status", ["pending", "approved"])
def test_drift_and_security_syncs_leave_a_deploy_change_untouched(db, deploy_payload, status):
    """The increment's central property.

    `approved` is the case that matters most: it is both inside reconcile's sweep
    (which spares only `resolved`/`wontfix`) and the status the change-window
    executor pulls.
    """
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    item.status = status
    db.commit()

    reconcile(db, sync_req([an_escalation()], "drift"))
    reconcile(db, sync_req([], "security"))
    reconcile(db, sync_req([], "rotation"))

    db.refresh(item)
    assert item.status == status
    resolved = db.scalars(
        select(ChangeEvent).where(
            ChangeEvent.item_id == item.id, ChangeEvent.event_type == "resolved"
        )
    ).all()
    assert resolved == []


def test_the_drift_sweep_still_resolves_its_own_absent_items(db, deploy_payload):
    """The control: the exclusion above must not have switched the sweep off."""
    propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    reconcile(db, sync_req([an_escalation()], "drift"))
    reconcile(db, sync_req([], "drift"))
    drift = db.scalar(select(ChangeItem).where(ChangeItem.source == "drift"))
    assert drift is not None and drift.status == "resolved"


def test_a_sync_cannot_declare_the_proposed_source(db, deploy_payload):
    """`SyncRequest.source` is caller-declared free text, so scoping alone is not a
    guarantee: an empty batch claiming source="deploy" would otherwise resolve every
    deploy change at once."""
    propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    with pytest.raises(ProposedSourceError):
        reconcile(db, sync_req([], "deploy"))
    item = db.scalar(select(ChangeItem).where(ChangeItem.source == "deploy"))
    assert item is not None and item.status == "pending"


def test_sync_route_refuses_the_proposed_source_with_422(client, m2m):
    r = client.post(
        "/api/sync",
        json={
            "generated_at": "2026-08-10T03:00:00Z",
            "source_report": "x.json",
            "escalations": [],
            "source": "deploy",
        },
        headers=m2m,
    )
    assert r.status_code == 422
    assert "cannot be reconciled" in r.json()["detail"]


def test_the_handoff_watchdog_cannot_reach_a_deploy_change(db, deploy_payload):
    """Asserted against the watchdog directly, not inferred from reconcile refusing
    to call it that way — "unreachable because its only caller checks first" is not a
    property a future caller inherits."""
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    item.status = "handed_off"
    item.handed_off_at = datetime.now(UTC) - timedelta(days=365)
    db.commit()

    for source in ("drift", "security", "rotation", "deploy"):
        revert_stale_handoffs(
            db,
            now=datetime.now(UTC),
            source=source,
            seen_identities={item.identity},
            max_age_days=1,
        )
    db.refresh(item)
    assert item.status == "handed_off"
