"""POST /api/items/{id}/deploy-supersession -- a failed rollout a later green one has passed.

A deploy record whose rollout FAILED stays approved forever, because nothing settles a failure,
yet the next green rollout of the same repository serves a build that contains its commit. The
route retires it, and like `deploy-retirement` it takes coordinates rather than a status and can
only reach `resolved`. Each refusal below is a positive guard on the record's own observation.
"""

import pytest

from app.deploy_retirement import RETIRED_STATUS, SUPERSEDED_EVENT
from app.models import ChangeEvent, ChangeItem

FAILED_COMMIT = "06f9268b5160d3d064f1f2e63d7f36faa2cb06df"
LATER_COMMIT = "191ec5a2" + "0" * 32


def _observation(**overrides) -> dict:
    body = {
        "target_repository": "AlobarQuest/change-manager",
        "pull_request_number": 42,
        "merge_commit_sha": FAILED_COMMIT,
        "merged_at": "2026-08-10T19:51:00+00:00",
        "workflow_path": ".github/workflows/deploy.yml",
        "workflow_revision": "a47d4b187c93971a5b5915ce87a963bd4ef35e30",
        "workflow_attestation": "revision_confirmed",
        "rollout_job": "build-and-deploy",
        "rollout_job_conclusion": "failure",
        "trigger_step": "Trigger Coolify redeploy",
        "trigger_step_conclusion": "failure",
        "run_id": 31426195637,
        "run_attempt": 1,
        "run_url": "https://github.com/AlobarQuest/change-manager/actions/runs/31426195637",
        "run_conclusion": "failure",
        "run_concluded_at": "2026-08-10T19:55:00+00:00",
        "observed_at": "2026-08-10T20:00:00+00:00",
        "actor": "deploy-watcher",
    }
    body.update(overrides)
    return body


@pytest.fixture()
def record(client, m2m, deploy_payload):
    return client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()


def _observe(client, m2m, item_id, **overrides):
    response = client.post(
        f"/api/items/{item_id}/deploy-observation", json=_observation(**overrides), headers=m2m
    )
    assert response.status_code == 201
    return response


def _supersede(client, m2m, item_id, **overrides):
    body = {
        "pull_request_number": 42,
        "superseding_run_id": 31426999999,
        "superseding_commit": LATER_COMMIT,
        "actor": "deploy-watcher",
        **overrides,
    }
    return client.post(f"/api/items/{item_id}/deploy-supersession", json=body, headers=m2m)


@pytest.fixture()
def failed(client, m2m, record):
    """A record whose only observation is a failed rollout."""
    _observe(client, m2m, record["id"])
    return record


def test_a_failed_rollout_superseded_resolves_the_record(client, m2m, failed, db):
    response = _supersede(client, m2m, failed["id"])
    assert response.status_code == 200
    assert response.json()["status"] == RETIRED_STATUS

    item = db.get(ChangeItem, failed["id"])
    assert item is not None and item.status == RETIRED_STATUS
    assert item.decided_by == "deploy-watcher" and item.decided_at is not None

    events = db.query(ChangeEvent).filter(ChangeEvent.item_id == failed["id"]).all()
    superseded = [e for e in events if e.event_type == SUPERSEDED_EVENT]
    assert len(superseded) == 1
    assert superseded[0].to_status == RETIRED_STATUS
    assert superseded[0].detail is not None
    assert "31426999999" in superseded[0].detail and LATER_COMMIT in superseded[0].detail
    assert FAILED_COMMIT in superseded[0].detail


def test_a_terminal_record_answers_200_unchanged(client, m2m, failed, db):
    assert _supersede(client, m2m, failed["id"]).status_code == 200
    second = _supersede(client, m2m, failed["id"])
    assert second.status_code == 200
    assert second.json()["status"] == RETIRED_STATUS

    events = db.query(ChangeEvent).filter(ChangeEvent.item_id == failed["id"]).all()
    assert len([e for e in events if e.event_type == SUPERSEDED_EVENT]) == 1


def test_a_wontfix_record_is_left_as_a_human_left_it(client, m2m, failed, db):
    item = db.get(ChangeItem, failed["id"])
    assert item is not None
    item.status = "wontfix"
    item.decided_by = "devon"
    db.commit()

    assert _supersede(client, m2m, failed["id"]).status_code == 200
    db.refresh(item)
    assert item.status == "wontfix" and item.decided_by == "devon"


def test_another_pull_request_is_refused(client, m2m, failed, db):
    response = _supersede(client, m2m, failed["id"], pull_request_number=99)
    assert response.status_code == 409
    item = db.get(ChangeItem, failed["id"])
    assert item is not None and item.status != RETIRED_STATUS


def test_a_non_deploy_record_is_refused(client, m2m, db):
    from datetime import UTC, datetime

    item = ChangeItem(
        identity="prod::some-rule::abc",
        instance="prod",
        rule_key="some-rule",
        source="security",
        status="pending",
        kind="drift",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        reasoning="something drifted",
        risk="caution",
        target_repository="alobarquest/change-manager",
        pull_request_number=42,
        plan={},
    )
    db.add(item)
    db.commit()

    assert _supersede(client, m2m, item.id).status_code == 409
    db.refresh(item)
    assert item.status == "pending"


def test_a_successful_rollout_is_refused(client, m2m, record, db):
    _observe(
        client,
        m2m,
        record["id"],
        rollout_job_conclusion="success",
        trigger_step_conclusion="success",
        run_conclusion="success",
    )
    item = db.get(ChangeItem, record["id"])
    assert item is not None
    # Settlement resolved it on the green observation; reopen it so only the verdict guard can
    # refuse, and the terminal replay cannot mask a missing one.
    item.status = "approved"
    db.commit()

    assert _supersede(client, m2m, record["id"]).status_code == 409
    db.refresh(item)
    assert item.status == "approved"


def test_no_observation_is_refused(client, m2m, record, db):
    assert _supersede(client, m2m, record["id"]).status_code == 409
    item = db.get(ChangeItem, record["id"])
    assert item is not None and item.status != RETIRED_STATUS


def test_the_failed_commit_cannot_supersede_itself(client, m2m, failed, db):
    response = _supersede(client, m2m, failed["id"], superseding_commit=FAILED_COMMIT.upper())
    assert response.status_code == 409
    item = db.get(ChangeItem, failed["id"])
    assert item is not None and item.status != RETIRED_STATUS


def test_the_route_rejects_a_status_field(client, m2m, failed):
    response = _supersede(client, m2m, failed["id"], status="approved")
    assert response.status_code == 422


def test_an_unknown_item_is_a_404(client, m2m):
    assert _supersede(client, m2m, 4242).status_code == 404
