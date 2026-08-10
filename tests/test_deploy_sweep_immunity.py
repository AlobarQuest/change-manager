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
from app.identity import rule_key_of, stable_identity
from app.models import ChangeEvent, ChangeItem
from app.reconcile import _resolve_absent, reconcile
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


def test_the_resolve_sweep_itself_skips_a_proposed_item(db, deploy_payload):
    """Asserted one level below `reconcile`, on purpose.

    `reconcile` refuses a proposed source at its entry, so a test driving `reconcile`
    passes whether or not the sweep carries its own exclusion — which is exactly how
    a guard ends up resting entirely on a check in its caller. Nothing reaches the
    sweep this way in production today; the point is that if anything ever does, the
    sweep still refuses.
    """
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    assert _resolve_absent(db, source="deploy", seen_identities=set()) == 0
    db.refresh(item)
    assert item.status == "pending"


def test_the_resolve_sweep_still_resolves_a_derived_item(db):
    """The control for the assertion above: same call, derived source, does resolve."""
    reconcile(db, sync_req([an_escalation()], "drift"))
    assert _resolve_absent(db, source="drift", seen_identities=set()) == 1


def colliding_escalation(repo="AlobarQuest/change-manager", pr=42):
    """A drift escalation whose computed identity IS a deploy record's.

    `stable_identity` is f"{instance}::{rule_key}::{uuid}" and `deploy_identity` is
    f"deploy::{repo}::{pr}" — one namespace, and all three drift fields are free text.
    Nothing about this batch is malformed and it declares `source="drift"`, which the
    entry refusal permits.
    """
    return EscalationIn(
        # The deploy key case-folds the repository, so a colliding batch spells it
        # that way. Every test using this asserts the identities are equal BEFORE
        # calling reconcile — otherwise a change to either scheme silently turns this
        # into a batch that collides with nothing and a guard that is never reached.
        proposal_id=f"{repo.lower()}:whatever",
        instance="deploy",
        target=TargetIn(provider="coolify", resource_type="application", uuid=str(pr), name="x"),
        risk="safe",
        kind="question",
        reasoning="a batch that looks entirely ordinary",
        plan={"root_cause": "n/a", "steps": ["coolify_deploy the app"]},
    )


def test_a_drift_batch_cannot_adopt_a_deploy_record_by_colliding_on_identity(db, deploy_payload):
    """The guards key on `source`; the upsert that WRITES `source` keys on identity.

    Refusing `req.source` alone left the join key open: this batch declares
    source="drift" honestly, lands on the deploy row by identity, and — before this
    refusal — the refresh rewrote `source` to "drift", after which every guard in
    `app.sources` read a column the sync had just changed and the record was listed
    and claimable by the change-window executor.
    """
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    assert item.identity == "deploy::alobarquest/change-manager::42"

    # The batch really does collide — asserted, not assumed.
    e = colliding_escalation()
    assert stable_identity(e.instance, rule_key_of(e.proposal_id), e.target.uuid) == item.identity

    with pytest.raises(ProposedSourceError):
        reconcile(db, sync_req([e], "drift"))

    db.rollback()
    item = db.scalar(select(ChangeItem).where(ChangeItem.source == "deploy"))
    assert item is not None
    assert item.source == "deploy" and item.lane == "deploy" and item.plan == {}


def test_a_colliding_batch_is_refused_whole_rather_than_partly_applied(db, deploy_payload):
    """The refusal raises before `reconcile` commits, so an honest escalation sharing
    the batch is not half-written."""
    propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    with pytest.raises(ProposedSourceError):
        reconcile(db, sync_req([an_escalation(), colliding_escalation()], "drift"))
    db.rollback()
    assert db.scalar(select(ChangeItem).where(ChangeItem.source == "drift")) is None


def test_a_proposal_will_not_adopt_another_pipelines_identity(db, client, m2m, deploy_payload):
    """The mirror. A drift item already holding the identity gets a legible refusal
    rather than a conflict listing every deploy column as 'differing'."""
    now = datetime.now(UTC)
    db.add(
        ChangeItem(
            identity="deploy::alobarquest/change-manager::42",
            instance="deploy",
            rule_key="AlobarQuest/change-manager",
            resource_uuid="42",
            resource_name="x",
            risk="safe",
            kind="question",
            reasoning="already here",
            plan={},
            status="pending",
            source="drift",
            first_seen_at=now,
            last_seen_at=now,
        )
    )
    db.commit()
    r = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    assert r.status_code == 409
    assert "held by a 'drift' item" in r.json()["detail"]


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
