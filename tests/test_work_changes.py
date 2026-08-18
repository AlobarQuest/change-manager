"""The work-proposal pipeline (ADR-0026), and the three properties it must and must not have.

The first test in this file is the acceptance test for the whole increment: the 04:00
change-window executor must not see a work item. Everything else exists because the property
being asserted has an inverse that must ALSO hold, and no single case discriminates both ways.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import ChangeItem
from app.sources import POLICY_APPROVED_SOURCES, PROPOSED_SOURCES, WORK_SOURCE

_WORK_PAYLOAD = {
    "package_id": "orchestrator-ruff-markdown-exclude",
    "package_revision": 1,
    "package_source_repository": "AlobarQuest/intent-packages",
    "risk": "caution",
    "reasoning": "ruff 0.16 formats Markdown code blocks; the estate decided to exclude them",
    "actor": "test",
}


def work_payload(**overrides) -> dict:
    return {**_WORK_PAYLOAD, **overrides}


def _approve(client: TestClient, m2m: dict[str, str], item_id: int):
    return client.post(f"/api/items/{item_id}/approve", json={"actor": "devon"}, headers=m2m)


def _propose(client: TestClient, m2m: dict[str, str], **overrides):
    return client.post("/api/work-changes", json=work_payload(**overrides), headers=m2m)


# --------------------------------------------------------------------------------------
# THE ACCEPTANCE TEST
# --------------------------------------------------------------------------------------


def test_the_0400_executor_call_does_not_see_an_approved_work_item(
    client: TestClient, m2m: dict[str, str], deploy_payload
) -> None:
    """Replay the executor's EXACT call and show the work item absent.

    `ChangeMgrClient.getApproved()` in infraops-mcp-server is
    `GET /api/items?status=approved` -- no source filter -- and `runWindow` then drops only
    `source === 'security'` before handing every remaining item to an LLM agent holding
    production Coolify tools. That filter is a denylist, so a source it predates is INCLUDED by
    default and the withholding has to happen here.

    The control is the drift item: it is in the same response, approved, on the same call. Its
    presence is what makes the work item's absence evidence of a filter rather than of an empty
    database -- a probe that returns nothing because it asked wrongly reports "safe" in exactly
    the same shape as one that works.
    """
    drift = client.post(
        "/api/sync",
        json={
            "generated_at": "2026-08-18T00:00:00Z",
            "source_report": "r",
            "escalations": [
                {
                    "proposal_id": "coolify.enable_healthcheck:abc",
                    "instance": "prod",
                    "target": {"provider": "coolify", "type": "app", "uuid": "u1", "name": "n1"},
                    "risk": "low",
                    "kind": "config",
                    "reasoning": "health check missing",
                    "plan": {},
                }
            ],
        },
        headers=m2m,
    )
    assert drift.status_code == 200, drift.text
    drift_id = client.get("/api/items", headers=m2m).json()[0]["id"]
    assert _approve(client, m2m, drift_id).status_code == 200

    work_id = _propose(client, m2m).json()["id"]
    assert _approve(client, m2m, work_id).status_code == 200
    deploy_id = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()["id"]

    # The executor's call, verbatim.
    listed = client.get("/api/items?status=approved", headers=m2m).json()
    ids = {it["id"] for it in listed}
    sources = {it["source"] for it in listed}

    assert drift_id in ids, "the control is missing: this probe is not reading anything"
    assert work_id not in ids, "the 04:00 executor can see a work item"
    assert deploy_id not in ids, "the 04:00 executor can see a deploy item"
    assert sources == {"drift"}

    # And what the executor does next, on what it did get: `runWindow` drops `security` only.
    survives_the_denylist = [it for it in listed if it["source"] != "security"]
    assert {it["id"] for it in survives_the_denylist} == {drift_id}


def test_naming_the_source_is_how_the_carry_sees_what_the_executor_cannot(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """The same withholding must not hide the record from the carry, or nothing can carry it.

    `GET /api/items` applies the exclusion only in the `else` branch of the source filter, so a
    caller that NAMES the pipeline is served. That asymmetry is the whole mechanism, and a
    change that withheld the source unconditionally would pass the acceptance test above while
    making the record unreachable by anything.
    """
    work_id = _propose(client, m2m).json()["id"]
    assert _approve(client, m2m, work_id).status_code == 200

    named = client.get("/api/items?status=approved&source=work", headers=m2m).json()
    assert [it["id"] for it in named] == [work_id]
    assert named[0]["package_id"] == _WORK_PAYLOAD["package_id"]
    assert named[0]["package_revision"] == 1
    assert named[0]["package_source_repository"] == "AlobarQuest/intent-packages"


# --------------------------------------------------------------------------------------
# THE VOCABULARY SPLIT -- every property needs BOTH directions
# --------------------------------------------------------------------------------------


def test_policy_approved_sources_is_a_strict_subset_of_proposed_sources() -> None:
    """The direction that fails silently is a new source copied into the wrong set.

    A source in `POLICY_APPROVED_SOURCES` but not in `PROPOSED_SOURCES` would be governed by
    the deploy policy and still offered to the 04:00 agent. A source in neither would be swept
    by reconcile. Strictness is what says the two sets are not drifting toward being one.
    """
    assert POLICY_APPROVED_SOURCES < PROPOSED_SOURCES
    assert WORK_SOURCE in PROPOSED_SOURCES
    assert WORK_SOURCE not in POLICY_APPROVED_SOURCES


def test_a_human_can_approve_a_work_item(client: TestClient, m2m: dict[str, str]) -> None:
    """The carry's precondition. Keyed on the wider set this is a 409 and the lane is dead."""
    item_id = _propose(client, m2m).json()["id"]
    response = _approve(client, m2m, item_id)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    assert response.json()["decided_by"] == "devon"


def test_a_caller_still_cannot_approve_a_deploy_item(
    client: TestClient, m2m: dict[str, str], deploy_payload
) -> None:
    """The inverse of the test above, and neither one alone discriminates.

    The first passes if the guard were deleted outright; this one passes if it were keyed on
    the wider set. Together they pin the split rather than either end of it.
    """
    item_id = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()["id"]
    # Move it off `approved` first, so this is a refusal rather than a no-op on a conforming row.
    client.post(f"/api/items/{item_id}/defer", json={"actor": "devon"}, headers=m2m)
    response = _approve(client, m2m, item_id)
    assert response.status_code == 409
    assert "approved by policy conformance" in response.json()["detail"]


def test_a_work_item_carries_no_deploy_policy_objections(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """`objections` fails closed to `target_repository_unreadable` on a record with no repository.

    Projected onto a work proposal that reads as a record failing to conform to a policy that
    was never about it -- the estate's "not applicable is a different answer from not met",
    which it has now rediscovered four times.
    """
    item = _propose(client, m2m).json()
    assert item["policy_objections"] == []
    assert item["landing_conditions"] is None


def test_a_deploy_item_still_carries_its_policy_projection(
    client: TestClient, m2m: dict[str, str], deploy_payload
) -> None:
    """The inverse: re-keying must not have emptied the projection for the source it is for."""
    item = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()
    assert item["landing_conditions"] is not None


def test_claim_refuses_a_work_item(client: TestClient, m2m: dict[str, str]) -> None:
    """Nothing in the change-window lanes is authorized to execute proposed work.

    The listing withholding is the first door and this is the second. The executor skips an
    item whose claim fails, so with only the listing guard a caller that named the source could
    still drive one into `in_progress`.
    """
    item_id = _propose(client, m2m).json()["id"]
    assert _approve(client, m2m, item_id).status_code == 200
    response = client.post(f"/api/items/{item_id}/claim", json={"actor": "executor"}, headers=m2m)
    assert response.status_code == 409
    assert "no authorized executor" in response.json()["detail"]


def test_outcome_refuses_a_work_item(client: TestClient, m2m: dict[str, str]) -> None:
    """The third door. `outcome` writes a ChangeAttempt asserting an agent APPLIED the change,
    and that event ships to the tamper-evident chain -- it is unreachable in practice only
    because the executor skips a failed claim, which is not a property a future caller inherits.
    """
    item_id = _propose(client, m2m).json()["id"]
    response = client.post(
        f"/api/items/{item_id}/outcome", json={"outcome": "done", "actor": "executor"}, headers=m2m
    )
    assert response.status_code == 409
    assert "no authorized executor" in response.json()["detail"]


def test_reconcile_refuses_a_batch_naming_the_work_source(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """A work item is asserted once and appears in no scan, so a sweep would resolve it."""
    response = client.post(
        "/api/sync",
        json={
            "generated_at": "2026-08-18T00:00:00Z",
            "source_report": "r",
            "escalations": [],
            "source": "work",
        },
        headers=m2m,
    )
    assert response.status_code == 422
    assert "proposed, not derived" in response.json()["detail"]


def test_a_drift_batch_does_not_resolve_an_absent_work_item(
    client: TestClient, m2m: dict[str, str], db: Session
) -> None:
    """The structural half of the same guard, asserted where it is true.

    `reconcile` refuses a batch that NAMES the source, so a test driving it through the source
    could not tell whether the sweep's own exclusion is present -- which is how a guard ends up
    resting entirely on a check in its caller. A `drift` batch reaches the sweep legitimately.
    """
    work_id = _propose(client, m2m).json()["id"]
    client.post(
        "/api/sync",
        json={"generated_at": "2026-08-18T00:00:00Z", "source_report": "r", "escalations": []},
        headers=m2m,
    )
    reloaded = db.get(ChangeItem, work_id)
    assert reloaded is not None
    assert reloaded.status == "pending"


# --------------------------------------------------------------------------------------
# THE INGRESS
# --------------------------------------------------------------------------------------


def test_an_identical_proposal_replays(client: TestClient, m2m: dict[str, str]) -> None:
    first = _propose(client, m2m)
    second = _propose(client, m2m)
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]


def test_a_different_proposal_for_the_same_revision_is_refused(
    client: TestClient, m2m: dict[str, str]
) -> None:
    _propose(client, m2m)
    response = _propose(client, m2m, reasoning="something else entirely")
    assert response.status_code == 409
    assert "reasoning" in response.json()["detail"]


def test_two_revisions_of_one_package_are_two_records(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """A package revision is a distinct approved artifact with its own canonical hash.

    Keyed on the package alone, the second would silently replay the first and the carry would
    prepare an intake for the wrong revision.
    """
    first = _propose(client, m2m, package_revision=1)
    second = _propose(client, m2m, package_revision=2)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_the_identity_is_case_folded(client: TestClient, m2m: dict[str, str]) -> None:
    """GitHub repository names are case-insensitive and the package id is an exact string.

    Without folding, a proposal differing only in case is a second record naming one intake,
    and the carry would prepare it twice.
    """
    first = _propose(client, m2m)
    assert first.status_code == 201
    # A case-variant lands on the SAME key, so it is compared against the stored row -- and
    # `package_source_repository` is an asserted field, so a differing case is a conflict rather
    # than a second record. Either answer proves the fold; a 201 would prove its absence.
    second = _propose(client, m2m, package_source_repository="alobarquest/intent-packages")
    assert second.status_code == 409, "a case-variant landed on a different key"
    assert "package_source_repository" in second.json()["detail"]
    assert len(client.get("/api/items?source=work", headers=m2m).json()) == 1


def test_the_item_stores_the_repository_as_written(client: TestClient, m2m: dict[str, str]) -> None:
    """Only the KEY is folded. The stored value is what the carry passes to the orchestrator."""
    item = _propose(client, m2m).json()
    assert item["package_source_repository"] == "AlobarQuest/intent-packages"


def test_a_proposal_cannot_adopt_an_identity_another_pipeline_holds(
    client: TestClient, m2m: dict[str, str], db: Session
) -> None:
    """`identity` is one namespace across every pipeline and every part of it is free text.

    Without this the field-by-field comparison reports every work column as differing, which is
    fail-closed but unreadable -- and a `source` this route then rewrote would move a drift
    record into a pipeline nothing sweeps.
    """
    held = ChangeItem(
        identity="work::alobarquest/intent-packages::orchestrator-ruff-markdown-exclude::1",
        instance="prod",
        rule_key="whatever",
        risk="low",
        kind="config",
        reasoning="a drift item that spelled a work identity",
        plan={},
        source="drift",
        first_seen_at=datetime(2026, 8, 18, tzinfo=UTC),
        last_seen_at=datetime(2026, 8, 18, tzinfo=UTC),
    )
    db.add(held)
    db.commit()
    response = _propose(client, m2m)
    assert response.status_code == 409
    assert "held by a 'drift' change" in response.json()["detail"]
    reloaded = db.get(ChangeItem, held.id)
    assert reloaded is not None
    assert reloaded.source == "drift", "the proposal rewrote another pipeline's source"


def test_the_route_refuses_a_payload_with_no_package(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """The locator is what makes the record carryable; without it there is nothing to carry."""
    payload = work_payload()
    del payload["package_id"]
    assert client.post("/api/work-changes", json=payload, headers=m2m).status_code == 422


def test_the_route_forbids_extra_fields(client: TestClient, m2m: dict[str, str]) -> None:
    """A caller that believes it is setting `plan` should learn so rather than have it dropped."""
    response = client.post("/api/work-changes", json=work_payload(plan={"steps": []}), headers=m2m)
    assert response.status_code == 422


def test_a_revision_of_zero_is_refused(client: TestClient, m2m: dict[str, str]) -> None:
    assert (
        client.post(
            "/api/work-changes", json=work_payload(package_revision=0), headers=m2m
        ).status_code
        == 422
    )


def test_a_boolean_revision_is_refused(client: TestClient, m2m: dict[str, str]) -> None:
    """pydantic's lax mode reads `true` as 1, filing the proposal against revision 1."""
    assert (
        client.post(
            "/api/work-changes", json=work_payload(package_revision=True), headers=m2m
        ).status_code
        == 422
    )


def test_a_bare_repository_name_is_refused(client: TestClient, m2m: dict[str, str]) -> None:
    payload = work_payload(package_source_repository="intent-packages")
    assert client.post("/api/work-changes", json=payload, headers=m2m).status_code == 422


def test_the_record_is_created_pending(client: TestClient, m2m: dict[str, str]) -> None:
    """The route reaches exactly one status, and it is the one every record starts at."""
    item = _propose(client, m2m).json()
    assert item["status"] == "pending"
    assert item["source"] == "work"
    assert item["lane"] == "work"


def test_package_subject_is_none_for_every_other_source(
    client: TestClient, m2m: dict[str, str], db: Session, deploy_payload
) -> None:
    """Keyed on WORK_SOURCE, not on PROPOSED_SOURCES -- the care `names_a_merge` documents."""
    deploy_id = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()["id"]
    work_id = _propose(client, m2m).json()["id"]
    deploy_item = db.get(ChangeItem, deploy_id)
    work_item = db.get(ChangeItem, work_id)
    assert deploy_item is not None and work_item is not None
    assert deploy_item.package_subject is None
    assert work_item.package_subject == (
        "orchestrator-ruff-markdown-exclude",
        1,
        "AlobarQuest/intent-packages",
    )
    assert work_item.merge_subject is None
