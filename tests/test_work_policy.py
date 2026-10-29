"""Policy approval of standing `work` records: dependency updates and credential rotations.

`work` stays outside `POLICY_APPROVED_SOURCES`: a source-wide policy would make rotation and
app-change records unapprovable by anyone. The policy is per RECORD, so every test pairs a
conforming record with a non-conforming one that differs in exactly one fact.
"""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import work_policy
from app.deploy_policy import current, inert_landing_dict
from app.models import ChangeEvent, ChangeItem
from app.work_policy import WORK_POLICY_ACTOR, objections

_INERT = "AlobarQuest/orchestrator"
_CONFORMING = {
    "package_id": "orchestrator-bump-ruff",
    "package_source_repository": "AlobarQuest/intent-packages",
    "risk": "caution",
    "target_repository": _INERT,
    "change_class": "dependency-update",
}


def _payload(**overrides) -> dict:
    return {
        "package_revision": 1,
        "reasoning": "dependabot bump failed in an inert repository",
        "actor": "bump-proposer",
        **_CONFORMING,
        **overrides,
    }


def _propose(client: TestClient, m2m: dict[str, str], **overrides):
    return client.post("/api/work-changes", json=_payload(**overrides), headers=m2m)


def test_a_conforming_work_record_is_approved_by_policy(
    db: Session, client: TestClient, m2m: dict[str, str]
) -> None:
    response = _propose(client, m2m)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["decided_by"] == WORK_POLICY_ACTOR == "work-policy"
    assert body["target_repository"] == _INERT
    assert body["change_class"] == "dependency-update"
    events = db.scalars(
        select(ChangeEvent).where(
            ChangeEvent.item_id == body["id"], ChangeEvent.event_type == "approved"
        )
    ).all()
    assert len(events) == 1
    assert events[0].actor == WORK_POLICY_ACTOR
    assert f"policy v{current().version}" in (events[0].detail or "")


@pytest.mark.parametrize(
    "overrides",
    [
        {"change_class": "app-change"},
        {"change_class": None},
        {"target_repository": None},
        {"target_repository": "AlobarQuest/not-in-policy"},
        {"risk": "high"},
        {"package_source_repository": "AlobarQuest/somewhere-else"},
    ],
    ids=["class", "no-class", "no-repo", "unlisted-repo", "risk", "source"],
)
def test_a_nonconforming_work_record_stays_pending(
    client: TestClient, m2m: dict[str, str], overrides: dict
) -> None:
    response = _propose(client, m2m, **overrides)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"
    assert response.json()["decided_by"] is None


def test_a_record_without_the_new_fields_is_unchanged(
    client: TestClient, m2m: dict[str, str]
) -> None:
    body = _payload()
    del body["target_repository"], body["change_class"]
    response = client.post("/api/work-changes", json=body, headers=m2m)
    assert response.status_code == 201
    assert response.json()["status"] == "pending"


def test_a_replay_with_the_fields_approves_a_pending_record(
    client: TestClient, m2m: dict[str, str]
) -> None:
    body = _payload()
    del body["target_repository"], body["change_class"]
    first = client.post("/api/work-changes", json=body, headers=m2m).json()
    assert first["status"] == "pending"

    replay = _propose(client, m2m)
    assert replay.status_code == 200
    assert replay.json()["id"] == first["id"]
    assert replay.json()["status"] == "approved"
    assert replay.json()["decided_by"] == WORK_POLICY_ACTOR


def test_the_new_fields_are_not_asserted(client: TestClient, m2m: dict[str, str]) -> None:
    first = _propose(client, m2m, target_repository="AlobarQuest/not-in-policy").json()
    replay = _propose(client, m2m, target_repository=_INERT, change_class="app-change")
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first["id"]
    # The first cause stands: policy is not re-run against fields the replay changed.
    assert replay.json()["target_repository"] == "AlobarQuest/not-in-policy"
    assert replay.json()["status"] == "pending"


def test_policy_never_revokes_or_overrides_a_decision(
    client: TestClient, m2m: dict[str, str]
) -> None:
    item_id = _propose(client, m2m).json()["id"]
    client.post(f"/api/items/{item_id}/defer", json={"actor": "devon"}, headers=m2m)
    replay = _propose(client, m2m)
    assert replay.json()["status"] == "deferred"
    assert replay.json()["decided_by"] == "devon"


def test_a_person_may_still_approve_a_nonconforming_work_record(
    client: TestClient, m2m: dict[str, str], db: Session
) -> None:
    item_id = _propose(client, m2m, change_class="app-change").json()["id"]
    item = db.get(ChangeItem, item_id)
    assert item is not None and item.human_may_approve is True
    response = client.post(f"/api/items/{item_id}/approve", json={"actor": "devon"}, headers=m2m)
    assert response.status_code == 200, response.text
    assert response.json()["decided_by"] == "devon"


# What the orchestrator's rotation proposer sends: no `target_repository` key at all.
_ROTATION = {
    "package_id": "rotation-openrouter-generic",
    "package_source_repository": "AlobarQuest/intent-packages",
    "risk": "caution",
    "change_class": "credential-rotation",
}


def _propose_rotation(client: TestClient, m2m: dict[str, str], **overrides):
    body = {**_payload(), **_ROTATION, **overrides}
    body.pop("target_repository", None)
    if "target_repository" in overrides:
        body["target_repository"] = overrides["target_repository"]
    return client.post("/api/work-changes", json=body, headers=m2m)


def test_a_standing_rotation_record_is_approved_by_policy(
    db: Session, client: TestClient, m2m: dict[str, str]
) -> None:
    """ADR-0055 amendment 16: the package revision a named person approved is the one click."""
    response = _propose_rotation(client, m2m)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "approved"
    assert body["decided_by"] == WORK_POLICY_ACTOR
    # The deploy policy permitted nothing about a rotation, so no version of it is recorded.
    assert body["policy_version"] is None
    event = db.scalars(
        select(ChangeEvent).where(
            ChangeEvent.item_id == body["id"], ChangeEvent.event_type == "approved"
        )
    ).one()
    assert "standing credential rotation" in (event.detail or "")
    assert "deploy policy" not in (event.detail or "")


@pytest.mark.parametrize(
    "overrides",
    [
        {"change_class": None},
        {"target_repository": _INERT},
        {"risk": "high"},
        {"package_source_repository": "AlobarQuest/somewhere-else"},
        {"package_id": "rotation-"},
        {"package_id": "rotation-Openrouter"},
        {"package_id": "x-rotation-openrouter"},
        {"package_id": "rotation_openrouter"},
        {"package_id": "orchestrator-bump-ruff"},
    ],
    ids=[
        "no-class",
        "repo",
        "risk",
        "source",
        "empty-credential",
        "upper-case",
        "prefixed",
        "underscore",
        "not-rotation",
    ],
)
def test_a_nonconforming_rotation_record_stays_pending(
    client: TestClient, m2m: dict[str, str], overrides: dict
) -> None:
    response = _propose_rotation(client, m2m, **overrides)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"


def test_a_rotation_named_bump_is_judged_as_a_bump() -> None:
    """A dependency-update package whose id happens to start `rotation-` gets the population
    check: the class decides which rules apply, never the package's name."""
    item = ChangeItem(
        **{**_CONFORMING, "package_id": "rotation-x-bump", "target_repository": "AlobarQuest/x"}
    )
    assert objections(item) == ["target_repository_not_in_policy"]


def test_a_pending_rotation_record_replayed_with_its_class_is_approved(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """A record proposed before the class was sent fills it on replay and is then approved."""
    first = _propose_rotation(client, m2m, change_class=None).json()
    assert first["status"] == "pending"
    replay = _propose_rotation(client, m2m)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first["id"]
    assert replay.json()["status"] == "approved"


def test_a_work_record_renders_without_a_pull_request(
    client: TestClient, m2m: dict[str, str]
) -> None:
    item_id = _propose(client, m2m).json()["id"]
    from tests.test_work_changes import _dev_login

    _dev_login()
    html = client.get(f"/items/{item_id}").text
    assert "#None" not in html
    assert "Deploying merge" not in html


def test_the_inert_list_is_read_from_the_current_deploy_policy() -> None:
    inert = inert_landing_dict(current())
    assert inert is not None and "alobarquest/orchestrator" in inert["repositories"]
    item = ChangeItem(
        package_source_repository="AlobarQuest/intent-packages",
        risk="caution",
        target_repository="ALOBARQUEST/Orchestrator",
        change_class="dependency-update",
    )
    assert objections(item) == []


def test_a_malformed_target_repository_is_refused(client: TestClient, m2m: dict[str, str]) -> None:
    assert _propose(client, m2m, target_repository="not a repo").status_code == 422


def test_reactivating_a_wontfix_record_lets_a_conforming_replay_approve_it(
    client: TestClient, m2m: dict[str, str]
) -> None:
    item_id = _propose(client, m2m, change_class="app-change").json()["id"]
    client.post(f"/api/items/{item_id}/wontfix", json={"actor": "devon"}, headers=m2m)
    reactivated = client.post(
        f"/api/items/{item_id}/reactivate", json={"actor": "devon"}, headers=m2m
    )
    assert reactivated.json()["status"] == "pending"
    # The stored class stands, so the replay cannot conform; policy leaves it for a person.
    assert _propose(client, m2m).json()["status"] == "pending"

    other = _propose(client, m2m, package_id="other-pkg").json()["id"]
    client.post(f"/api/items/{other}/wontfix", json={"actor": "devon"}, headers=m2m)
    client.post(f"/api/items/{other}/reactivate", json={"actor": "devon"}, headers=m2m)
    replay = _propose(client, m2m, package_id="other-pkg")
    assert replay.json()["status"] == "approved"
    assert replay.json()["decided_by"] == WORK_POLICY_ACTOR


@pytest.mark.parametrize(
    "repository",
    [
        pytest.param("AlobarQuest/brain", id="brain"),
        pytest.param("AlobarQuest/change-manager", id="change-manager"),
        pytest.param("alobarquest/BRAIN", id="brain-case-variant"),
    ],
)
def test_deploying_repository_record_is_approved(
    client: TestClient, m2m: dict[str, str], repository: str
) -> None:
    response = _propose(client, m2m, package_id="bump-deploying", target_repository=repository)
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "approved"
    assert response.json()["decided_by"] == WORK_POLICY_ACTOR


def _item(repository: str) -> ChangeItem:
    return ChangeItem(
        package_source_repository="AlobarQuest/intent-packages",
        risk="caution",
        target_repository=repository,
        change_class="dependency-update",
    )


@pytest.mark.parametrize("repository", ["AlobarQuest/not-in-policy", "AlobarQuest/brain-x"])
def test_record_outside_both_populations_stays_pending(repository: str) -> None:
    assert objections(_item(repository)) == ["target_repository_not_in_policy"]


def test_a_policy_without_an_inert_block_approves_only_deploying_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(work_policy, "current", lambda: replace(current(), inert_landing=None))
    assert objections(_item("AlobarQuest/brain")) == []
    assert objections(_item(_INERT)) == ["target_repository_not_in_policy"]


def test_current_policy_landing_populations_are_disjoint() -> None:
    """Checks the CURRENT policy only: the module keeps no older versions, and each version
    that becomes current is checked here when it ships."""
    policy = current()
    inert = policy.inert_landing.repositories if policy.inert_landing else frozenset()
    assert policy.repositories & inert == frozenset()
