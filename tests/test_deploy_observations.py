"""ADR-0019 increment 2 — recording what a rollout did, and refusing what is not one.

Two of these tests exist because adversarial review killed a design, and they are marked so:
`test_a_second_merge_commit_is_RECORDED` and `test_a_raced_failure_is_not_a_failure`. Both pin a
behaviour whose opposite was implemented first and looked correct.
"""

from datetime import UTC, datetime

import pytest

from app.deploy_observations import (
    REACHED_NO,
    REACHED_UNKNOWN,
    REACHED_YES,
    VERDICT_ABSENT,
    VERDICT_FAILED,
    VERDICT_SUCCESS,
    VERDICT_UNKNOWN,
    current_observation,
    merge_commits_observed,
    production_reached_for,
    verdict_for,
)
from app.models import ChangeItem, DeployObservation

MERGE = "06f9268b5160d3d064f1f2e63d7f36faa2cb06df"
OTHER = "191ec5a2" + "0" * 32
REVISION = "a47d4b187c93971a5b5915ce87a963bd4ef35e30"
JOB = "build-and-deploy"


def observation(**overrides) -> dict:
    body = {
        "target_repository": "AlobarQuest/change-manager",
        "pull_request_number": 42,
        "merge_commit_sha": MERGE,
        "merged_at": "2026-08-10T19:51:00+00:00",
        "workflow_path": ".github/workflows/deploy.yml",
        "workflow_revision": REVISION,
        "workflow_attestation": "revision_confirmed",
        "rollout_job": "build-and-deploy",
        "rollout_job_conclusion": "success",
        "trigger_step": "Trigger Coolify redeploy",
        "trigger_step_conclusion": "success",
        "run_id": 31426195637,
        "run_attempt": 1,
        "run_url": "https://github.com/AlobarQuest/change-manager/actions/runs/31426195637",
        "run_conclusion": "success",
        "run_concluded_at": "2026-08-10T19:55:00+00:00",
        "observed_at": "2026-08-10T20:00:00+00:00",
        "actor": "deploy-watcher",
    }
    body.update(overrides)
    return body


def no_run(**overrides) -> dict:
    """The `absent` shape: no run, and therefore no run detail of any kind."""
    body = observation(
        run_id=None,
        run_attempt=None,
        run_url=None,
        run_conclusion=None,
        run_concluded_at=None,
        rollout_job_conclusion=None,
        trigger_step_conclusion=None,
    )
    body.update(overrides)
    return body


@pytest.fixture
def item(client, m2m, deploy_payload) -> int:
    response = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m)
    assert response.status_code == 201
    return response.json()["id"]


# -- the derivations, as pure functions -------------------------------------------------------


class TestVerdict:
    def test_the_four_conclusion_buckets(self):
        assert verdict_for("success") == VERDICT_SUCCESS
        for failed in ("failure", "timed_out", "startup_failure"):
            assert verdict_for(failed) == VERDICT_FAILED
        for inconclusive in ("cancelled", "skipped", "neutral", "action_required", "stale"):
            assert verdict_for(inconclusive) == VERDICT_UNKNOWN
        assert verdict_for(None) == VERDICT_ABSENT

    def test_a_conclusion_github_invents_later_degrades_rather_than_reading_green(self):
        assert verdict_for("some_future_value") == VERDICT_UNKNOWN

    def test_a_raced_failure_is_not_a_failure(self):
        """KILLED A DESIGN. Both repositories redeploy a floating tag with no concurrency group.

        change-manager's verify step polls production for ten minutes waiting to see its own
        commit; a second merge landing mid-poll wins the tag and the first run exits 1. That is a
        lost race, and `failed` is the verdict that licenses a rollback of a build that is fine.
        Merges 108 and 131 seconds apart have already happened here.
        """
        assert verdict_for("failure", raced=False) == VERDICT_FAILED
        assert verdict_for("failure", raced=True) == VERDICT_UNKNOWN
        # A race does not turn a success into a doubt, and cannot manufacture one either.
        assert verdict_for("success", raced=True) == VERDICT_SUCCESS


class TestProductionReached:
    def test_no_requires_positive_evidence_that_the_rollout_job_did_not_run(self):
        """Two sources of that evidence, and no others: no run at all, or a SKIPPED job.

        "the job conclusion is absent" was a third until review measured its population: a
        skipped job is reported as `skipped`, so absence only ever meant registry drift.
        """
        assert production_reached_for(None, None, classified=True, ran_at_all=False) == REACHED_NO
        assert production_reached_for("skipped", None, classified=True, job_name=JOB) == REACHED_NO
        # And the branch that was removed now answers unknown, which is the point.
        assert (
            production_reached_for(None, None, classified=True, ran_at_all=True) == REACHED_UNKNOWN
        )

    def test_yes_requires_the_trigger_step_to_have_succeeded(self):
        assert (
            production_reached_for("success", "success", classified=True, job_name=JOB)
            == REACHED_YES
        )
        assert (
            production_reached_for("failure", "success", classified=True, job_name=JOB)
            == REACHED_YES
        )

    def test_a_failed_trigger_step_is_unknown_and_deliberately_not_no(self):
        """brain's trigger step is a loop over four webhooks under `bash -e`.

        A failure there means an unknown PREFIX of them fired, so calling it `no` — the value
        that says "nothing was deployed, do not roll back" — would be the same overstatement as
        calling a liveness poll a revision check.
        """
        assert (
            production_reached_for("failure", "failure", classified=True, job_name=JOB)
            == REACHED_UNKNOWN
        )

    def test_an_unclassified_workflow_cannot_answer_at_all(self):
        """Nobody transcribed which job talks to production, so the names looked at may be wrong."""
        assert (
            production_reached_for("success", "success", classified=False, job_name=JOB)
            == REACHED_UNKNOWN
        )

    def test_NO_RUN_answers_no_even_when_the_workflow_is_unclassified(self):
        """Added because a mutation control survived without it.

        The `ran_at_all` branch and the `job_conclusion is None` branch both answer `no` for a
        settled classified observation, so deleting the first reddened nothing — and the case
        it actually protects is this one: with no run AND no transcription, the classification
        guard fires first and answers `unknown` for the one situation that is certain. No run
        means nothing executed, whoever did or did not classify the workflow.
        """
        assert production_reached_for(None, None, classified=False, ran_at_all=False) == REACHED_NO
        assert production_reached_for(None, None, classified=True, ran_at_all=False) == REACHED_NO


class TestReduction:
    """The rule that turns a contradicting append-only history into one answer."""

    def _row(self, ident, run_id, attempt, verdict, sha=MERGE):
        return DeployObservation(
            id=ident,
            item_id=1,
            observation_key=str(ident),
            merge_commit_sha=sha,
            merged_at=datetime.now(UTC),
            verdict=verdict,
            production_reached=REACHED_YES,
            workflow_path="w",
            workflow_attestation="unknown",
            run_id=run_id,
            run_attempt=attempt,
            observed_at=datetime.now(UTC),
            observed_by="t",
            recorded_at=datetime.now(UTC),
        )

    def test_nothing_observed_is_no_answer(self):
        assert current_observation([]) is None

    def test_a_run_beats_no_run_however_they_are_ordered(self):
        """`absent` is only ever evidence about the moment it was taken.

        GitHub indexes runs a little after the fact, so a pass at 09:00 legitimately sees none
        and a pass at 09:30 sees a green one. Both rows are true; only one is the answer.
        """
        absent = self._row(1, None, None, VERDICT_ABSENT)
        found = self._row(2, 99, 1, VERDICT_SUCCESS)
        assert current_observation([absent, found]) is found
        assert current_observation([found, absent]) is found

    def test_a_run_beats_no_run_even_when_the_ABSENCE_WAS_RECORDED_LATER(self):
        """Added because a mutation control survived without it.

        With the absent row appended first, latest-by-id happens to give the same answer, so
        deleting the run-beats-no-run rule reddened nothing — the ids encoded the answer. The
        case the rule protects is the other order: a run observed at 09:00, then a pass at
        09:30 that GitHub answered with nothing. A verdict of `absent` must not overwrite a run
        that was seen, and the later row is exactly the one latest-by-id would pick.
        """
        found = self._row(1, 99, 1, VERDICT_SUCCESS)
        absent_later = self._row(2, None, None, VERDICT_ABSENT)
        assert current_observation([found, absent_later]) is found

    def test_the_later_attempt_of_a_rerun_wins(self):
        first = self._row(1, 99, 1, VERDICT_FAILED)
        rerun = self._row(2, 99, 2, VERDICT_SUCCESS)
        assert current_observation([first, rerun]) is rerun
        assert current_observation([rerun, first]) is rerun

    def test_divergent_merge_commits_are_reported_in_first_seen_order(self):
        rows = [
            self._row(1, 99, 1, VERDICT_SUCCESS, sha=MERGE),
            self._row(2, 98, 1, VERDICT_SUCCESS, sha=OTHER),
            self._row(3, 97, 1, VERDICT_SUCCESS, sha=MERGE),
        ]
        assert merge_commits_observed(rows) == [MERGE, OTHER]
        assert merge_commits_observed(rows[:1]) == [MERGE]


# -- the route --------------------------------------------------------------------------------


class TestRecording:
    def test_a_settled_run_is_recorded_with_a_derived_verdict(self, client, m2m, item):
        response = client.post(
            f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m
        )
        assert response.status_code == 201
        body = response.json()
        assert body["verdict"] == VERDICT_SUCCESS
        assert body["production_reached"] == REACHED_YES
        assert body["run_id"] == 31426195637

    def test_re_observing_the_same_attempt_replays(self, client, m2m, item):
        first = client.post(
            f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m
        )
        again = client.post(
            f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m
        )
        assert (first.status_code, again.status_code) == (201, 200)
        assert again.json()["id"] == first.json()["id"]

    def test_re_observing_no_run_also_replays(self, client, m2m, item):
        """The `absent` key carries no NULLs, so it dedupes.

        Keyed on the columns instead, `(item, NULL, NULL)` would be distinct from itself on both
        Postgres and SQLite and every pass over a change whose merge produced no run would append
        another row, forever.
        """
        first = client.post(f"/api/items/{item}/deploy-observation", json=no_run(), headers=m2m)
        again = client.post(f"/api/items/{item}/deploy-observation", json=no_run(), headers=m2m)
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["verdict"] == VERDICT_ABSENT
        assert first.json()["production_reached"] == REACHED_NO
        assert again.json()["id"] == first.json()["id"]

    def test_two_attempts_that_concluded_IDENTICALLY_are_still_two_rows(self, client, m2m, item):
        """The discriminating form, added because a mutation control survived without it.

        The re-run test below varies the conclusion, so the content digest alone distinguishes
        the two rows and dropping `attempt` from the key reddened nothing. A re-run that
        concluded the same way is still a different attempt and still a separate thing that
        happened.
        """
        first = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_attempt=1),
            headers=m2m,
        )
        second = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_attempt=2),
            headers=m2m,
        )
        assert (first.status_code, second.status_code) == (201, 201)
        page = client.get(f"/api/items/{item}/deploy-observations", headers=m2m).json()
        assert [o["run_attempt"] for o in page["observations"]] == [1, 2]

    def test_a_rerun_appends_rather_than_replacing(self, client, m2m, item):
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_attempt=1, run_conclusion="failure"),
            headers=m2m,
        )
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_attempt=2, run_conclusion="success"),
            headers=m2m,
        )
        page = client.get(f"/api/items/{item}/deploy-observations", headers=m2m).json()
        assert [o["verdict"] for o in page["observations"]] == [VERDICT_FAILED, VERDICT_SUCCESS]
        assert page["current"]["run_attempt"] == 2
        assert page["current"]["verdict"] == VERDICT_SUCCESS

    def test_a_second_merge_commit_is_RECORDED_and_reported_not_refused(self, client, m2m, item):
        """KILLED A DESIGN, and this is the sharper of the two.

        The first implementation froze the merge commit at the first observation, reasoning that
        a pull request merges once. But `merge_commit_sha` is caller-supplied, change-manager has
        no GitHub egress to check it, and GitHub populates that field on OPEN pull requests with
        a throwaway test-merge commit that satisfies every shape check — item 44's own subject,
        PR #42, carries one today. With the table append-only, no supersession, no delete route
        and `PATCH` limited to `pr_url`, one wrong POST would have made the true verdict
        unrecordable against that change FOREVER. Reporting a divergence costs a finding;
        refusing one costs the record.
        """
        client.post(f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m)
        second = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(merge_commit_sha=OTHER, run_id=1),
            headers=m2m,
        )
        assert second.status_code == 201
        page = client.get(f"/api/items/{item}/deploy-observations", headers=m2m).json()
        assert page["merge_commits_observed"] == [MERGE, OTHER]

    def test_observing_moves_nothing(self, client, m2m, item):
        """The whole reason increment 1's executor guards need no change."""
        before = client.get(f"/api/items/{item}", headers=m2m).json()["status"]
        client.post(f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m)
        after = client.get(f"/api/items/{item}", headers=m2m).json()["status"]
        assert before == after == "pending"

    def test_the_history_event_carries_the_whole_finding(self, client, m2m, item):
        """`change_events` survives the downgrade that drops the observation table."""
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_conclusion="failure"),
            headers=m2m,
        )
        events = client.get("/api/events", headers=m2m).json()["events"]
        observed = [e for e in events if e["event_type"] == "deploy_observed"]
        assert len(observed) == 1
        detail = observed[0]["detail"]
        wanted = (MERGE, "verdict=failed", "production_reached=yes", REVISION, "31426195637")
        for fragment in wanted:
            assert fragment in detail


class TestRefusals:
    def test_a_derived_item_has_no_rollout_to_observe(self, client, m2m, db):
        from app.identity import stable_identity

        now = datetime.now(UTC)
        drift = ChangeItem(
            identity=stable_identity("prod", "rule", "uuid"),
            instance="prod",
            rule_key="rule",
            risk="caution",
            kind="k",
            reasoning="r",
            plan={},
            status="approved",
            source="drift",
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(drift)
        db.commit()
        response = client.post(
            f"/api/items/{drift.id}/deploy-observation", json=observation(), headers=m2m
        )
        assert response.status_code == 409
        assert "names no pull request" in response.json()["detail"]

    def test_an_observation_about_a_different_pull_request_is_refused(self, client, m2m, item):
        response = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(pull_request_number=41),
            headers=m2m,
        )
        assert response.status_code == 409
        assert "::41" in response.json()["detail"]

    def test_an_observation_about_a_different_repository_is_refused(self, client, m2m, item):
        response = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(target_repository="AlobarQuest/brain"),
            headers=m2m,
        )
        assert response.status_code == 409

    def test_the_repository_comparison_is_case_folded_like_the_identity(self, client, m2m, item):
        response = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(target_repository="alobarquest/CHANGE-manager"),
            headers=m2m,
        )
        assert response.status_code == 201

    def test_the_caller_may_not_assert_a_verdict(self, client, m2m, item):
        for field in ("verdict", "production_reached"):
            response = client.post(
                f"/api/items/{item}/deploy-observation",
                json={**observation(), field: "success"},
                headers=m2m,
            )
            assert response.status_code == 422, field

    def test_a_run_that_has_not_concluded_is_not_a_verdict(self, client, m2m, item):
        response = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_conclusion=None),
            headers=m2m,
        )
        assert response.status_code == 422

    def test_run_detail_without_a_run_is_refused(self, client, m2m, item):
        response = client.post(
            f"/api/items/{item}/deploy-observation",
            json=no_run(rollout_job_conclusion="success"),
            headers=m2m,
        )
        assert response.status_code == 422

    def test_a_naive_timestamp_is_a_422_and_never_a_500(self, client, m2m, item):
        for field in ("observed_at", "merged_at", "run_concluded_at"):
            response = client.post(
                f"/api/items/{item}/deploy-observation",
                json=observation(**{field: "2026-08-10T20:00:00"}),
                headers=m2m,
            )
            assert response.status_code == 422, field

    def test_merged_at_is_required(self, client, m2m, item):
        body = observation()
        del body["merged_at"]
        response = client.post(f"/api/items/{item}/deploy-observation", json=body, headers=m2m)
        assert response.status_code == 422

    def test_an_unclassified_attestation_word_is_refused(self, client, m2m, item):
        response = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(workflow_attestation="liveness_confirmed"),
            headers=m2m,
        )
        assert response.status_code == 422

    def test_a_sha_shaped_like_a_ref_is_refused(self, client, m2m, item):
        for bad in ("main", "06f9268", MERGE + "0", "Z" * 40):
            response = client.post(
                f"/api/items/{item}/deploy-observation",
                json=observation(merge_commit_sha=bad),
                headers=m2m,
            )
            assert response.status_code == 422, bad

    def test_a_missing_item_is_a_404(self, client, m2m):
        response = client.post(
            "/api/items/99999/deploy-observation", json=observation(), headers=m2m
        )
        assert response.status_code == 404

    def test_the_route_is_m2m_guarded(self, client, item):
        anon = client.post(f"/api/items/{item}/deploy-observation", json=observation())
        assert anon.status_code == 401
        assert client.get(f"/api/items/{item}/deploy-observations").status_code == 401


class TestExecutorStillRefused:
    """Increment 1's guards, re-asserted after adding a route that writes to the same item.

    Replaying the executor's exact calls rather than asserting the intent, because the whole
    hazard is that a new door reopens an old one.
    """

    def test_the_executor_still_cannot_see_claim_or_close_a_deploy_change(self, client, m2m, item):
        client.post(f"/api/items/{item}/approve", json={"actor": "devon"}, headers=m2m)
        client.post(f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m)

        listed = client.get("/api/items?status=approved", headers=m2m).json()
        assert item not in [i["id"] for i in listed]

        claim = client.post(f"/api/items/{item}/claim", json={"actor": "x"}, headers=m2m)
        assert claim.status_code == 409
        assert (
            client.post(
                f"/api/items/{item}/outcome", json={"outcome": "done", "actor": "x"}, headers=m2m
            ).status_code
            == 409
        )
        assert (
            client.post(f"/api/items/{item}/handoff", json={"actor": "x"}, headers=m2m).status_code
            == 409
        )

    def test_a_derived_item_is_still_listed_and_still_claimable(self, client, m2m, db):
        """The control. Without it the test above passes for a repository that lists nothing."""
        from app.identity import stable_identity

        now = datetime.now(UTC)
        drift = ChangeItem(
            identity=stable_identity("prod", "rule", "uuid-2"),
            instance="prod",
            rule_key="rule",
            risk="caution",
            kind="k",
            reasoning="r",
            plan={},
            status="approved",
            source="drift",
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(drift)
        db.commit()
        listed = client.get("/api/items?status=approved", headers=m2m).json()
        assert drift.id in [i["id"] for i in listed]
        claim = client.post(f"/api/items/{drift.id}/claim", json={"actor": "x"}, headers=m2m)
        assert claim.status_code == 200


class TestReviewFixes:
    """One test per KILL from the post-implementation review."""

    def test_re_observing_the_same_run_with_DIFFERENT_FACTS_appends(self, client, m2m, item):
        """The repair for this system's own named residual was a silent no-op without this.

        The key returned the stored row before deriving anything, so when a workflow edit
        degraded an observation to `unknown` and somebody transcribed the new revision — the
        documented fix — a second pass over the same run attempt replayed and the record stayed
        `unknown` forever: append-only, no supersession, no delete, `PATCH` limited to `pr_url`.
        That is the dead end the merge-commit freeze was removed for, one level down, firing on
        an ordinary event rather than a wrong POST.
        """
        first = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(
                workflow_attestation="unknown",
                workflow_revision=None,
                rollout_job=None,
                rollout_job_conclusion=None,
                trigger_step=None,
                trigger_step_conclusion=None,
            ),
            headers=m2m,
        )
        assert first.status_code == 201
        assert first.json()["workflow_attestation"] == "unknown"
        assert first.json()["production_reached"] == REACHED_UNKNOWN

        # Same item, same run, same attempt — and the registry now knows the revision.
        second = client.post(
            f"/api/items/{item}/deploy-observation", json=observation(), headers=m2m
        )
        assert second.status_code == 201, "a changed fact must append, never replay"
        assert second.json()["workflow_attestation"] == "revision_confirmed"
        assert second.json()["production_reached"] == REACHED_YES

        page = client.get(f"/api/items/{item}/deploy-observations", headers=m2m).json()
        assert len(page["observations"]) == 2
        assert page["current"]["workflow_attestation"] == "revision_confirmed"

    def test_identical_facts_still_replay(self):
        """The control. Without it the fix above is "append always", which is not idempotent."""
        from app.deploy_observations import fact_digest, observation_key
        from app.schemas import DeployObservationIn

        a = DeployObservationIn(**observation())
        b = DeployObservationIn(**observation())
        assert fact_digest(a) == fact_digest(b)
        assert observation_key(1, MERGE, 9, 1, fact_digest(a)) == observation_key(
            1, MERGE, 9, 1, fact_digest(b)
        )
        c = DeployObservationIn(**observation(run_conclusion="failure"))
        assert fact_digest(c) != fact_digest(a)

    def test_a_job_the_run_does_not_have_is_UNKNOWN_never_no(self, client, m2m, item):
        """Registry drift must not read as "nothing was deployed, do not roll back".

        A skipped job is reported with `conclusion: "skipped"`, so the absent-job branch's only
        real population was drift — and it answered `no` about a rollout that may have
        succeeded, the exact inversion this axis exists to prevent.
        """
        assert (
            production_reached_for("success", "success", classified=True, job_name=None)
            == REACHED_UNKNOWN
        )
        drifted = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(
                rollout_job=None,
                rollout_job_conclusion=None,
                trigger_step=None,
                trigger_step_conclusion=None,
            ),
            headers=m2m,
        )
        assert drifted.status_code == 201
        assert drifted.json()["verdict"] == VERDICT_SUCCESS
        assert drifted.json()["production_reached"] == REACHED_UNKNOWN

    def test_a_skipped_job_is_still_a_confident_no(self):
        """The case the deleted branch was written for, which was always covered by this one."""
        assert (
            production_reached_for("skipped", None, classified=True, job_name="build-and-deploy")
            == REACHED_NO
        )

    def test_a_skipped_conclusion_with_NO_JOB_NAMED_is_not_a_no(self, client, m2m, item):
        """The discriminating form, added because a mutation control survived without it.

        Every other case here pairs an absent job name with an absent conclusion, where the
        drift guard and the fall-through both answer `unknown` — so forcing a job name at the
        call site changed nothing and the guard was untested. `no` must require the watcher to
        have actually identified the job whose conclusion it is reporting.
        """
        assert (
            production_reached_for("skipped", None, classified=True, job_name=None)
            == REACHED_UNKNOWN
        )
        recorded = client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(
                rollout_job=None,
                rollout_job_conclusion="skipped",
                trigger_step=None,
                trigger_step_conclusion=None,
            ),
            headers=m2m,
        )
        assert recorded.status_code == 201
        assert recorded.json()["production_reached"] == REACHED_UNKNOWN

    def test_there_is_no_current_answer_when_the_rows_disagree_about_the_landing(
        self, client, m2m, item
    ):
        """Run ids only increase, so a later observation at the WRONG commit always won.

        `current` would headline `success` for a landing that never happened, with the
        divergence sitting in unstyled prose four paragraphs below it.
        """
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(run_id=100, run_conclusion="failure"),
            headers=m2m,
        )
        client.post(
            f"/api/items/{item}/deploy-observation",
            json=observation(merge_commit_sha=OTHER, run_id=999),
            headers=m2m,
        )
        page = client.get(f"/api/items/{item}/deploy-observations", headers=m2m).json()
        assert len(page["merge_commits_observed"]) == 2
        assert page["current"] is None, "ambiguity must be reported as ambiguity"
