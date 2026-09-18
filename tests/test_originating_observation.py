"""Which observation caused a proposed record (the signal->work contract, clause C1).

The load-bearing test here is `test_replaying_a_pre_contract_*_record_with_a_cause_is_a_replay`,
once for each proposed ingress. Everything else here would still pass if the field were added to
`_ASSERTED_FIELDS`; those two are what distinguish the decision that was made from the one that
looks identical at the schema and would wedge both scheduled producers permanently.

The refusal cases come in pairs on purpose. A validator that accepted nothing would pass every
"is refused" assertion on its own, so each is read beside the canonical value it must accept.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.schemas import DeployChangeIn, WorkChangeIn

REPO = Path(__file__).resolve().parent.parent

CAUSE = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
OTHER_CAUSE = "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"

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


def _work_model(**overrides) -> dict:
    return work_payload(**overrides)


def _deploy_model(**overrides) -> dict:
    return {
        "target_repository": "AlobarQuest/change-manager",
        "pull_request_number": 42,
        "change_class": "dependency-update",
        "risk": "caution",
        "reasoning": "uvicorn floor bump; landing on main redeploys production",
        "acceptance_criteria": ["/api/health reports the merged commit within 10 minutes"],
        "rollback_plan": {"steps": ["revert the merge"]},
        "actor": "test",
        **overrides,
    }


_MODELS = [
    pytest.param(WorkChangeIn, _work_model, id="work"),
    pytest.param(DeployChangeIn, _deploy_model, id="deploy"),
]


# --------------------------------------------------------------------------------------
# THE SHAPE, ON BOTH SCHEMAS
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("model", "build"), _MODELS)
def test_a_canonical_observation_id_is_accepted_and_absence_is_not_an_error(model, build) -> None:
    """The positive control. Without it every refusal below is satisfied by refusing all."""
    named = model.model_validate(build(originating_observation_id=CAUSE))
    assert named.originating_observation_id == CAUSE
    # Absent and explicit-null are both "nothing recorded a cause", and the validator runs on
    # the second: a `None` branch that was missing would raise here rather than in the first.
    assert model.model_validate(build()).originating_observation_id is None
    explicit_null = model.model_validate(build(originating_observation_id=None))
    assert explicit_null.originating_observation_id is None


@pytest.mark.parametrize(("model", "build"), _MODELS)
def test_a_padded_observation_id_is_stripped_rather_than_refused(model, build) -> None:
    """The clause that makes `_required_text` load-bearing here rather than decoration.

    The regex alone already refuses blank, whitespace and zero-width values, so without this
    case every assertion about them would pass with the `_required_text` call deleted -- an
    unkillable clause sitting beside clauses that can fail, which is how a suite comes to report
    coverage it has not got. What the helper actually adds is the STRIP, matching the treatment
    `package_source_repository` and every other text field on these models already get.
    """
    padded = model.model_validate(build(originating_observation_id=f"  {CAUSE}\n"))
    assert padded.originating_observation_id == CAUSE


@pytest.mark.parametrize(("model", "build"), _MODELS)
@pytest.mark.parametrize(
    ("value", "why"),
    [
        ("", "an empty string is a producer that believes it is naming a cause"),
        ("   ", "whitespace is not a cause"),
        ("​", "a zero-width space renders as nothing and must not read as a cause"),
        ("not-a-uuid", "free text is not an observation id"),
        (CAUSE.upper(), "the orchestrator emits str(uuid), which is always lowercase"),
        ("{" + CAUSE + "}", "the braced spelling is a second spelling of one id"),
        ("urn:uuid:" + CAUSE, "the urn spelling is a third"),
        (CAUSE.replace("-", ""), "the hyphen-free spelling is a fourth"),
        (CAUSE + "-extra", "a canonical id with something appended is not canonical"),
    ],
)
def test_a_non_canonical_observation_id_is_refused(model, build, value, why) -> None:
    """The four spellings at the end are what make this a canonical-form check.

    `uuid.UUID()` accepts every one of them, so a parse-based validator would store four
    different strings for one observation and a later lookup would miss three of them.
    """
    with pytest.raises(ValidationError):
        model.model_validate(build(originating_observation_id=value))


# --------------------------------------------------------------------------------------
# THE WORK INGRESS
# --------------------------------------------------------------------------------------


def _propose_work(client: TestClient, m2m: dict[str, str], **overrides):
    return client.post("/api/work-changes", json=work_payload(**overrides), headers=m2m)


def _stored_work(client: TestClient, m2m: dict[str, str]) -> dict:
    items = client.get("/api/items?source=work", headers=m2m).json()
    assert len(items) == 1, items
    return items[0]


def test_a_proposed_work_record_carries_the_cause_it_named(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """The control on the explicit write.

    `originating_observation_id` is deliberately outside `_ASSERTED_FIELDS`, which is also the
    construction payload -- so the value reaches the row only because the constructor names it.
    Drop that one line and this test is the thing that dies.
    """
    created = _propose_work(client, m2m, originating_observation_id=CAUSE)
    assert created.status_code == 201, created.text
    assert created.json()["originating_observation_id"] == CAUSE
    assert _stored_work(client, m2m)["originating_observation_id"] == CAUSE


def test_a_work_record_may_name_no_cause(client: TestClient, m2m: dict[str, str]) -> None:
    assert _propose_work(client, m2m).status_code == 201
    assert _stored_work(client, m2m)["originating_observation_id"] is None


def test_replaying_a_pre_contract_work_record_with_a_cause_is_a_replay(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """THE DECISION, as a test: records 59-62 meeting a producer that has learned to observe.

    Every `work` record proposed before this column existed stores null, and `bump_proposer`
    re-proposes all of them on every scheduled pass. Were the cause an ASSERTED fact, this call
    would compare null against an id, raise `WorkChangeConflict`, and answer 409 -- which the
    producer classifies as a refusal, so it becomes a finding on every pass, forever, with no
    repair route: the row is write-once, its status is a human's alone, and no supersede route
    exists.

    It answers 200, and the record is left exactly as it was. Not back-filled: a replay may not
    retro-fit a cause onto a record proposed before anyone was naming one.
    """
    assert _propose_work(client, m2m).status_code == 201
    assert _stored_work(client, m2m)["originating_observation_id"] is None

    replay = _propose_work(client, m2m, originating_observation_id=CAUSE)

    assert replay.status_code == 200, replay.text
    assert replay.json()["originating_observation_id"] is None
    assert _stored_work(client, m2m)["originating_observation_id"] is None


def test_re_proposing_a_work_record_under_a_different_cause_is_a_replay(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """The cost of the decision above, asserted rather than left in a comment.

    A producer that named the wrong cause cannot correct it: the second proposal is a replay and
    the first cause stands. Stated here so that a later change making this a 409 has to delete a
    test that says why it is not one.
    """
    assert _propose_work(client, m2m, originating_observation_id=CAUSE).status_code == 201

    replay = _propose_work(client, m2m, originating_observation_id=OTHER_CAUSE)

    assert replay.status_code == 200, replay.text
    assert _stored_work(client, m2m)["originating_observation_id"] == CAUSE


def test_a_work_proposal_differing_in_an_asserted_fact_still_conflicts(
    client: TestClient, m2m: dict[str, str]
) -> None:
    """The discriminator for the two tests above: conflict detection still works.

    Without this, "a replay" is indistinguishable from "this ingress stopped comparing anything".
    """
    assert _propose_work(client, m2m, originating_observation_id=CAUSE).status_code == 201

    conflict = _propose_work(client, m2m, risk="high", originating_observation_id=CAUSE)

    assert conflict.status_code == 409, conflict.text
    assert "risk" in conflict.json()["detail"]


# --------------------------------------------------------------------------------------
# THE DEPLOY INGRESS
# --------------------------------------------------------------------------------------


def _propose_deploy(client: TestClient, m2m: dict[str, str], deploy_payload, **overrides):
    return client.post("/api/deploy-changes", json=deploy_payload(**overrides), headers=m2m)


def _stored_deploy(client: TestClient, m2m: dict[str, str]) -> dict:
    items = client.get("/api/items?source=deploy", headers=m2m).json()
    assert len(items) == 1, items
    return items[0]


def test_a_proposed_deploy_record_carries_the_cause_it_named(
    client: TestClient, m2m: dict[str, str], deploy_payload
) -> None:
    """The control on the explicit write, deploy side.

    `_proposed` selects `_PROPOSED_FIELDS` out of the body, so a field in neither tuple is
    dropped unless the constructor names it -- the inbound twin of a response model silently
    losing a key it does not declare.
    """
    created = _propose_deploy(client, m2m, deploy_payload, originating_observation_id=CAUSE)
    assert created.status_code == 201, created.text
    assert created.json()["originating_observation_id"] == CAUSE
    assert _stored_deploy(client, m2m)["originating_observation_id"] == CAUSE


def test_a_deploy_record_may_name_no_cause(
    client: TestClient, m2m: dict[str, str], deploy_payload
) -> None:
    assert _propose_deploy(client, m2m, deploy_payload).status_code == 201
    assert _stored_deploy(client, m2m)["originating_observation_id"] is None


def test_replaying_a_pre_contract_deploy_record_with_a_cause_is_a_replay(
    client: TestClient, m2m: dict[str, str], deploy_payload
) -> None:
    """The same decision on the larger population.

    `change_proposer` replays every deploy record it has proposed on every hourly pass, and the
    deploy lane is deliberately left non-conformant by this increment -- so this is the shape
    that would break first, and it would break hourly.

    Note the replay path here is NOT a no-op, unlike the work lane's: it refreshes the derived
    facts and re-runs the policy. The cause surviving that is what shows it is in neither tuple.
    """
    assert _propose_deploy(client, m2m, deploy_payload).status_code == 201
    assert _stored_deploy(client, m2m)["originating_observation_id"] is None

    replay = _propose_deploy(client, m2m, deploy_payload, originating_observation_id=CAUSE)

    assert replay.status_code == 200, replay.text
    assert _stored_deploy(client, m2m)["originating_observation_id"] is None


def test_re_proposing_a_deploy_record_under_a_different_cause_is_a_replay(
    client: TestClient, m2m: dict[str, str], deploy_payload
) -> None:
    assert (
        _propose_deploy(client, m2m, deploy_payload, originating_observation_id=CAUSE).status_code
        == 201
    )

    replay = _propose_deploy(client, m2m, deploy_payload, originating_observation_id=OTHER_CAUSE)

    assert replay.status_code == 200, replay.text
    assert _stored_deploy(client, m2m)["originating_observation_id"] == CAUSE


def test_a_deploy_proposal_differing_in_an_asserted_fact_still_conflicts(
    client: TestClient, m2m: dict[str, str], deploy_payload
) -> None:
    """The discriminator, deploy side."""
    assert (
        _propose_deploy(client, m2m, deploy_payload, originating_observation_id=CAUSE).status_code
        == 201
    )

    conflict = _propose_deploy(
        client, m2m, deploy_payload, risk="high", originating_observation_id=CAUSE
    )

    assert conflict.status_code == 409, conflict.text
    assert "risk" in conflict.json()["detail"]


# --------------------------------------------------------------------------------------
# THE MIGRATION
# --------------------------------------------------------------------------------------


def _alembic(db: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db}"},
        cwd=str(REPO),
        capture_output=True,
        text=True,
    )


def _columns(db: str) -> set[str]:
    return {r[1] for r in sqlite3.connect(db).execute("pragma table_info(change_items)").fetchall()}


def test_the_column_arrives_on_upgrade_and_leaves_on_downgrade() -> None:
    """Both directions, exercised rather than assumed.

    `downgrade()` is a column drop with no foreign key and no data to preserve, so this is one
    of the few cases where SQLite's silence about foreign keys costs nothing. It is still run:
    a downgrade nobody has ever executed is not a rollback path, it is a paragraph.
    """
    with tempfile.TemporaryDirectory() as d:
        db = os.path.join(d, "m.db")

        up = _alembic(db, "upgrade", "head")
        assert up.returncode == 0, up.stderr
        after_upgrade = _columns(db)

        down = _alembic(db, "downgrade", "2c3d4e5f6a7b")
        assert down.returncode == 0, down.stderr
        after_downgrade = _columns(db)

    assert "originating_observation_id" in after_upgrade
    assert "originating_observation_id" not in after_downgrade
    # The control: the downgrade removed THIS column and not the schema around it.
    assert {"package_id", "package_revision", "package_source_repository"} <= after_downgrade


def test_the_model_and_the_migrated_schema_agree() -> None:
    """A column on the model that no migration creates is a production-only failure.

    Every other test in this file runs against `Base.metadata.create_all`, which cannot see a
    missing migration; `entrypoint.sh` migrates.
    """
    from sqlalchemy import inspect

    from app.models import ChangeItem

    assert "originating_observation_id" in {c.name for c in inspect(ChangeItem).columns}
