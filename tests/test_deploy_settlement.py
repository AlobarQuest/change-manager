"""ADR-0022 — the watcher owns outcomes, so a confirmed rollout settles its change record.

The defect these pin: production item 52 recorded `verdict=success production_reached=yes
attests=revision_confirmed` twenty minutes after `alobarquest/change-manager` #50 landed, and
stayed `approved`. A change that had already happened went on authorising itself, with the
producer's retirement sweep reporting `skipped` because the pull request merged rather than closed.

Two of these are the increment's real subjects rather than coverage.
`test_a_replay_settles_a_record_whose_observation_predates_this_code` is the ONLY route by which
item 52 can ever settle -- its observation exists, so every future pass replays -- and a settlement
reachable from the created path alone would have shipped, passed, and never touched the record it
was built for. `test_a_divergent_history_settles_nothing` is the fact-not-absence rule at the one
place it bites: two merge commits mean there is no single answer, and one of the two rows saying
`success` is not the record's verdict.
"""

from datetime import UTC, datetime

import pytest

from app.deploy_observations import (
    REACHED_UNKNOWN,
    REACHED_YES,
    VERDICT_SUCCESS,
    current_observation,
    observations_for,
)
from app.deploy_settlement import (
    SETTLED_EVENT,
    SETTLED_STATUS,
    SETTLEMENT_ACTOR,
    landed_successfully,
    settle_landed_deploy_change,
)
from app.identity import stable_identity
from app.models import ChangeItem, DeployObservation

MERGE = "2ba9f7f2ef4121aef69153fc2e6dd248cfdcf33b"
OTHER = "06f9268b" + "0" * 32
REVISION = "a47d4b187c93971a5b5915ce87a963bd4ef35e30"


def observation(**overrides) -> dict:
    """The shape production item 52 actually carries: a rollout that confirmed the revision."""
    body = {
        "target_repository": "AlobarQuest/change-manager",
        "pull_request_number": 42,
        "merge_commit_sha": MERGE,
        "merged_at": "2026-08-13T08:55:00+00:00",
        "workflow_path": ".github/workflows/deploy.yml",
        "workflow_revision": REVISION,
        "workflow_attestation": "revision_confirmed",
        "rollout_job": "build-and-deploy",
        "rollout_job_conclusion": "success",
        "trigger_step": "Trigger Coolify redeploy",
        "trigger_step_conclusion": "success",
        "run_id": 31685940716,
        "run_attempt": 1,
        "run_url": "https://github.com/AlobarQuest/change-manager/actions/runs/31685940716",
        "run_conclusion": "success",
        "run_concluded_at": "2026-08-13T09:00:00+00:00",
        "observed_at": "2026-08-13T09:20:13+00:00",
        "actor": "deploy-watcher",
    }
    body.update(overrides)
    return body


@pytest.fixture()
def item(client, m2m, deploy_payload) -> int:
    response = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    assert response.status_code == 201
    return response.json()["id"]


def _status(client, m2m, item: int) -> str:
    return client.get(f"/api/items/{item}", headers=m2m).json()["status"]


def _events(client, m2m, item: int, event_type: str) -> list[dict]:
    events = client.get("/api/events", headers=m2m).json()["events"]
    return [e for e in events if e["item_id"] == item and e["event_type"] == event_type]


class TestTheSettlement:
    def test_a_confirmed_rollout_settles_the_record(self, client, m2m, item):
        response = client.post(
            f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m
        )
        assert response.status_code == 201
        assert response.json()["item_status"] == SETTLED_STATUS
        assert _status(client, m2m, item) == SETTLED_STATUS

    def test_the_event_names_the_fact_it_settled_on(self, client, m2m, db, item):
        """A machine closing a record a human may have approved is honest only if the chain says
        what it closed on, and by what."""
        client.post(f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m)
        settled = _events(client, m2m, item, SETTLED_EVENT)
        assert len(settled) == 1
        assert settled[0]["actor"] == SETTLEMENT_ACTOR
        assert settled[0]["to_status"] == SETTLED_STATUS
        assert "landed" in settled[0]["detail"]
        assert "AlobarQuest/change-manager#42" in settled[0]["detail"]
        # THE COLUMN, as well as the chain. `decided_by` answers who is answerable for the record's
        # current state and `change_events` answers how it got there — two different questions, and
        # a mutation deleting the two assignments left the whole suite green until this line.
        row = db.get(ChangeItem, item)
        assert row.decided_by == SETTLEMENT_ACTOR
        assert row.decided_at is not None

    def test_a_replay_settles_a_record_whose_observation_predates_this_code(
        self, client, m2m, db, item
    ):
        """THE CASE THIS INCREMENT EXISTS FOR, and the one a created-path settlement would miss.

        Production item 52's observation was written before any settlement existed, so its
        `observation_key` is already taken and every future watcher pass REPLAYS -- returning the
        stored row without deriving anything and writing nothing. A settlement wired only into the
        created path passes every other test in this file and never moves the record that forced
        ADR-0022.

        The unsettled-with-an-observation state is reached by holding the record `wontfix` for the
        first POST, because the route can no longer produce it any other way. The two assertions
        that discriminate are the 200 and the unchanged row count: without them this would pass on
        a second append.
        """
        held = db.get(ChangeItem, item)
        held.status = "wontfix"
        db.commit()
        first = client.post(
            f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m
        )
        assert first.status_code == 201
        assert first.json()["item_status"] == "wontfix"

        held.status = "approved"
        db.commit()
        before = len(observations_for(db, item))
        replay = client.post(
            f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m
        )
        assert replay.status_code == 200, "the same facts must replay, not append"
        assert len(observations_for(db, item)) == before, "a replay must write no row"
        assert replay.json()["item_status"] == SETTLED_STATUS

    def test_a_record_a_human_never_approved_still_settles(self, client, m2m, item):
        """`pending` is the ordinary state of a record whose pull request a person merged anyway.

        The change happened and its rollout confirmed, so there is no decision left to make and
        leaving it open only grows a queue nobody retires. `from_status` carries the history.
        """
        assert _status(client, m2m, item) == "pending"
        client.post(f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m)
        assert _status(client, m2m, item) == SETTLED_STATUS
        assert _events(client, m2m, item, SETTLED_EVENT)[0]["from_status"] == "pending"


class TestWhatDoesNotSettle:
    def test_an_unverified_rollout_settles_nothing(self, client, m2m, item):
        """THE ONE JUDGMENT IN THIS MODULE, and the estate has already measured why.

        A green run at an `rollout_unverified` revision proves a webhook answered 2xx, or that a
        domain was up while Coolify's rolling swap was still serving the OLD container. Settling on
        that asserts the change succeeded from evidence written down as unable to establish it.
        Every `alobarquest/brain` rollout is this, and so is every change-manager revision before
        `a47d4b18`.
        """
        response = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(workflow_attestation="rollout_unverified"),
            headers=m2m,
        )
        assert response.json()["verdict"] == VERDICT_SUCCESS, "the rollout did go green"
        assert response.json()["item_status"] == "pending"

    def test_an_unclassified_workflow_settles_nothing(self, client, m2m, item):
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(workflow_attestation="unknown"),
            headers=m2m,
        )
        assert _status(client, m2m, item) == "pending"

    def test_a_failed_rollout_settles_nothing(self, client, m2m, item):
        """The case that most needs the record left open: somebody must decide about a rollback."""
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_conclusion="failure"),
            headers=m2m,
        )
        assert _status(client, m2m, item) == "pending"

    def test_a_rollout_that_did_not_reach_production_settles_nothing(self, client, m2m, item):
        """Green, confirmed bytes, and no positive evidence production was told anything."""
        response = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(trigger_step_conclusion="failure"),
            headers=m2m,
        )
        assert response.json()["production_reached"] == REACHED_UNKNOWN
        assert response.json()["item_status"] == "pending"

    def test_a_divergent_history_settles_nothing(self, client, m2m, item):
        """SETTLE ON A FACT, NEVER ON ABSENCE — at the place the rule actually bites.

        Two merge commits mean the rows disagree about which landing they describe, so
        `current_observation` returns None and there is no verdict to settle on. One of the two
        rows saying `success` is not the record's answer, and a settlement that reached past the
        reduction would close a record on a landing that may never have happened.
        """
        first = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(merge_commit_sha=OTHER, run_id=1, run_conclusion="failure"),
            headers=m2m,
        )
        assert first.json()["item_status"] == "pending"
        second = client.post(
            f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m
        )
        assert second.status_code == 201
        page = client.get(f"/api/items/{item}/deploy-observations", headers=m2m).json()
        assert page["merge_commits_observed"] == [OTHER, MERGE]
        assert page["current"] is None
        assert second.json()["item_status"] == "pending"

    def test_a_human_decision_against_the_change_is_not_overridden(self, client, m2m, db, item):
        """`wontfix` is a person saying no. A machine settling it would be re-deciding."""
        held = db.get(ChangeItem, item)
        held.status = "wontfix"
        db.commit()
        client.post(f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m)
        assert _status(client, m2m, item) == "wontfix"
        assert not _events(client, m2m, item, SETTLED_EVENT)

    def test_a_settled_record_is_not_settled_twice(self, client, m2m, item):
        """The watcher records every hour; a settlement it already made must not become an event
        per pass."""
        client.post(f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m)
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_attempt=2, run_id=31685940717),
            headers=m2m,
        )
        assert len(_events(client, m2m, item, SETTLED_EVENT)) == 1

    def test_a_later_failure_is_recorded_and_does_not_reopen(self, client, m2m, item):
        """The stage-two question, answered in the direction ADR-0022 names.

        A re-run that fails after a settlement is a fact, and the table is append-only, so it is
        recorded. Reopening is a DECISION and this module records outcomes -- so the status holds
        and the contradiction is left visible: `current` reads `failed` while the record reads
        `resolved`, which is what the watcher reports.
        """
        client.post(f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m)
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_attempt=2, run_conclusion="failure"),
            headers=m2m,
        )
        page = client.get(f"/api/items/{item}/deploy-observations", headers=m2m).json()
        assert page["current"]["run_attempt"] == 2
        assert page["current"]["verdict"] == "failed"
        assert _status(client, m2m, item) == SETTLED_STATUS

    def test_a_derived_item_is_refused_by_the_source_guard_and_by_nothing_else(self, db):
        """The route refuses a drift item before this is reached, so the guard here is the SECOND
        one — and increment 1's lesson is that a guard whose only protection is another guard is an
        accident rather than a design.

        **The observation is seeded deliberately, and a mutation proved it necessary.** Written the
        obvious way — a bare drift item, called directly — the item has no observations, so the
        reduction refuses it and deleting the source guard leaves the test green. It discriminated
        nothing. With a confirmed rollout attached, the source check is the only thing left that can
        say no.
        """
        now = datetime.now(UTC)
        drift = ChangeItem(
            identity=stable_identity("prod", "rule", "uuid"),
            instance="prod",
            rule_key="rule",
            risk="caution",
            kind="k",
            reasoning="a drifted setting",
            source="drift",
            status="pending",
            plan={},
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(drift)
        db.flush()
        db.add(
            DeployObservation(
                item_id=drift.id,
                observation_key=f"{drift.id}:{MERGE}:1:1:seeded",
                merge_commit_sha=MERGE,
                merged_at=now,
                verdict=VERDICT_SUCCESS,
                production_reached=REACHED_YES,
                workflow_path=".github/workflows/deploy.yml",
                workflow_revision=REVISION,
                workflow_attestation="revision_confirmed",
                run_id=1,
                run_attempt=1,
                observed_at=now,
                observed_by="deploy-watcher",
                recorded_at=now,
            )
        )
        db.commit()
        assert landed_successfully(current_observation(observations_for(db, drift.id))) is True
        assert settle_landed_deploy_change(db, drift) is False
        assert drift.status == "pending"


class TestThePredicate:
    """`landed_successfully` is three positive clauses, and each has to be load-bearing."""

    @staticmethod
    def _row(**overrides) -> DeployObservation:
        values = {
            "verdict": VERDICT_SUCCESS,
            "production_reached": REACHED_YES,
            "workflow_attestation": "revision_confirmed",
        }
        values.update(overrides)
        return DeployObservation(**values)

    def test_all_three_together(self):
        assert landed_successfully(self._row()) is True

    @pytest.mark.parametrize(
        "field,value",
        [
            ("verdict", "failed"),
            ("verdict", "unknown"),
            ("verdict", "absent"),
            ("production_reached", "no"),
            ("production_reached", "unknown"),
            ("workflow_attestation", "rollout_unverified"),
            ("workflow_attestation", "unknown"),
        ],
    )
    def test_each_clause_alone_refuses(self, field, value):
        assert landed_successfully(self._row(**{field: value})) is False

    def test_no_observation_is_not_a_weak_yes(self):
        assert landed_successfully(None) is False


def test_the_api_reaches_the_appender_only_through_the_composition() -> None:
    """The settlement must run on every path into the observation write, so `app.api` must not
    hold a route to the appender that skips it.

    Asserted as an import fact rather than by reading source: `from app.deploy_observations import
    record_deploy_observation` would put the name on this module, and that is exactly the edit that
    would reintroduce a door the settlement does not sit behind.
    """
    import app.api

    assert not hasattr(app.api, "record_deploy_observation")
    assert hasattr(app.api, "record_rollout_and_settle")
