"""The 04:00 change-window executor's exact contract, pinned from this side.

`com.devon.change-window` (a LaunchAgent on the mini) runs infraops-mcp-server's
`change-mgr-cli run-window`, which makes THREE calls against an item
(`run-window.ts` getApproved / claim / postOutcome; `security-executor.ts` likewise):

    GET  /api/items?status=approved      (no source parameter)
    POST /api/items/{id}/claim
    POST /api/items/{id}/outcome

and hands whatever comes back — minus a `source === 'security'` DENYLIST — to an LLM
agent holding production Coolify tools. A denylist admits a source it predates, which
`rotation` already demonstrates. A deploying merge is landed by merging a pull
request; that agent cannot do that and would improvise against production instead.

These tests replay all three verbatim. The third is the one an earlier draft of this
file miscounted, and it was also the one left unguarded — the executor never reaches
it because it skips an item whose claim failed, which is exactly the kind of safety
this repository has twice written down as not being safety at all.
"""

from datetime import UTC, datetime

from app.deploy_changes import propose_deploy_change
from app.models import ChangeAttempt, ChangeItem
from app.schemas import DeployChangeIn


def approved_deploy_item(db, deploy_payload):
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    item.status = "approved"
    db.commit()
    return item


def test_the_executors_approved_listing_does_not_return_a_deploy_change(
    db, client, m2m, deploy_payload
):
    item = approved_deploy_item(db, deploy_payload)
    listed = client.get("/api/items?status=approved", headers=m2m).json()
    assert [i["id"] for i in listed] == []
    # Not a blanket hiding: a caller that names the pipeline still gets it.
    named = client.get("/api/items?status=approved&source=deploy", headers=m2m).json()
    assert [i["id"] for i in named] == [item.id]


def test_the_executor_cannot_claim_a_deploy_change(db, client, m2m, deploy_payload):
    item = approved_deploy_item(db, deploy_payload)
    r = client.post(
        f"/api/items/{item.id}/claim", json={"actor": "change-window-agent"}, headers=m2m
    )
    assert r.status_code == 409
    assert "no authorized executor" in r.json()["detail"]
    db.refresh(item)
    assert item.status == "approved"


def test_the_executor_cannot_post_an_outcome_on_a_deploy_change(db, client, m2m, deploy_payload):
    """The third call, which `claim` alone does not cover.

    `outcome` has no status precondition, so guarding only `claim` leaves it reachable
    on an unclaimed item — writing a ChangeAttempt and an `attempt_done` event that
    say an agent applied a deploy nothing performed, into a chain built to be
    tamper-evident.
    """
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    for outcome in ("done", "failed", "blocked", "skipped_conformant"):
        r = client.post(
            f"/api/items/{item.id}/outcome",
            json={"outcome": outcome, "actor": "change-window-agent"},
            headers=m2m,
        )
        assert r.status_code == 409, outcome
        assert "no authorized executor" in r.json()["detail"]
    db.refresh(item)
    assert item.status == "pending"
    assert db.query(ChangeAttempt).count() == 0


def test_a_deploy_change_cannot_be_handed_off(db, client, m2m, deploy_payload):
    """It carries no handoff brief, and `revert_stale_handoffs` is forbidden from
    rescuing it — so `handed_off` is a status no lane owns and no watchdog reaches."""
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    r = client.post(f"/api/items/{item.id}/handoff", json={"actor": "someone"}, headers=m2m)
    assert r.status_code == 409
    assert "no authorized executor" in r.json()["detail"]
    db.refresh(item)
    assert item.status == "pending"


def test_a_derived_item_is_still_listed_and_claimable(db, client, m2m):
    """The control: the guards above must not have closed the executor's real lane."""
    now = datetime.now(UTC)
    it = ChangeItem(
        identity="prod::572::db1",
        instance="prod",
        rule_key="572",
        resource_uuid="db1",
        resource_name="pg1",
        risk="safe",
        kind="question",
        reasoning="rule #572",
        plan={},
        status="approved",
        source="drift",
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(it)
    db.commit()

    listed = client.get("/api/items?status=approved", headers=m2m).json()
    assert [i["id"] for i in listed] == [it.id]
    claimed = client.post(f"/api/items/{it.id}/claim", json={"actor": "x"}, headers=m2m)
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "in_progress"
    done = client.post(
        f"/api/items/{it.id}/outcome", json={"outcome": "done", "actor": "x"}, headers=m2m
    )
    assert done.status_code == 200
    assert done.json()["status"] == "done"
