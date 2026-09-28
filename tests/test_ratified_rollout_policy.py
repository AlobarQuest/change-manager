"""The committed ratified-rollout projection cannot drift from the policy it projects.

The orchestrator reads `contracts/ratified_rollout_policy.json` at this repository's `main` as
DATA and compares it with the acceptance criteria and rollback plans it derives. That file is
therefore the cross-repo surface, and it is only honest while it equals what `current()` holds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.deploy_policy import (
    RATIFIED_ROLLOUT_POLICY_PATH,
    current,
    ratified_rollout_dict,
    render_ratified_rollout_policy,
)
from app.deploy_policy_history import REGISTRY

COMMITTED = Path(__file__).resolve().parent.parent / RATIFIED_ROLLOUT_POLICY_PATH


def test_the_committed_file_is_what_the_current_version_projects() -> None:
    assert COMMITTED.read_text(encoding="utf-8") == render_ratified_rollout_policy(current()), (
        "contracts/ratified_rollout_policy.json is stale; run "
        "`python -m scripts.write_ratified_rollout_policy` and commit the result"
    )


def test_the_projection_carries_exactly_what_objections_compares() -> None:
    """Each entry is the tuple and the mapping `objections` holds a record to, and the pin the
    landing party holds the rollout to -- nothing restated, nothing summarised."""
    policy = current()
    projected = json.loads(COMMITTED.read_text(encoding="utf-8"))

    assert projected["policy_version"] == policy.version
    assert set(projected["repositories"]) == set(policy.acceptance_criteria)
    for repository, entry in projected["repositories"].items():
        assert tuple(entry["acceptance_criteria"]) == policy.acceptance_criteria[repository]
        assert entry["rollback_plan"] == policy.rollback_plans[repository].as_stored()
        pin = policy.landing.rollout_workflows[repository]
        assert entry["rollout_workflow"] == {"path": pin.path, "blob_sha": pin.blob_sha}


@pytest.mark.parametrize("version", sorted(REGISTRY))
def test_every_retained_version_projects(version: int) -> None:
    """A version with criteria and no rollout pin would refuse rather than project a waiver."""
    policy = REGISTRY[version]
    if all(r in policy.landing.rollout_workflows for r in policy.acceptance_criteria):
        assert set(ratified_rollout_dict(policy)["repositories"]) == set(policy.acceptance_criteria)
    else:
        with pytest.raises(ValueError):
            ratified_rollout_dict(policy)
