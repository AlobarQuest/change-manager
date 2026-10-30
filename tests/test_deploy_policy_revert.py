"""Version 14: the SDS's own revert of a bad bump, approved by policy (Landing Part 3b).

When a Dependabot bump the orchestrator landed into a deploying repository is judged bad, the SDS
points production back at the previous image and opens a revert pull request through its Dispatch
App. That revert is a deploying merge, so it carries a record, and the record's class is
`dependency-revert`: a class of its own, because the bump's terms are the wrong ones for it -- its
remedy is to restore the bump, and it must not wait for the next change window while production is
pinned to an image the default branch no longer describes.

Each affirmative test here carries its control: the revert class must not loosen the bump's terms,
and the bump's terms must not admit a revert.
"""

import pytest

from app.deploy_policy import (
    CURRENT_VERSION,
    DEPENDENCY_REVERT,
    DISPATCH_APP,
    current,
    landing_conditions_dict,
    objections,
)
from app.deploy_policy_history import REGISTRY, policy_for

BRAIN = "alobarquest/brain"
CHANGE_MANAGER = "alobarquest/change-manager"
BUMP = "dependency-update"


class _Row:
    """A record as `objections` reads one: attributes, not a mapping."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


def revert_conformant(repository: str = CHANGE_MANAGER, **overrides) -> dict:
    """A revert record as `change_proposer` derives one: the repository's criteria, the revert's
    own remedy."""
    policy = current()
    return {
        "target_repository": repository,
        "pull_request_number": 71,
        "change_class": DEPENDENCY_REVERT,
        "risk": "caution",
        "reasoning": "the SDS reverts pull request #70 it judged bad",
        "acceptance_criteria": list(policy.acceptance_criteria[repository]),
        "rollback_plan": policy.class_rollback_plans[DEPENDENCY_REVERT][repository].as_stored(),
        "actor": "change-proposer",
        **overrides,
    }


def test_the_class_and_the_author_are_spelled_as_the_producer_and_github_spell_them():
    """`change_proposer` writes the class; GitHub's REST `pulls/{n}` answers the login. Both sit on
    the permitting side, so a misspelling under-permits: the revert waits for a person."""
    assert DEPENDENCY_REVERT == "dependency-revert"
    assert DISPATCH_APP == "alobar-sds-dispatch[bot]"


def test_version_fourteen_admits_the_revert_class_and_changes_nothing_else():
    v13, v14 = policy_for(13), policy_for(14)
    assert v13 is not None and v14 is not None
    assert v14 is current() and CURRENT_VERSION == 14

    # An EXACT union: `>=` would pass a version that admits every class.
    assert v14.change_classes == v13.change_classes | {DEPENDENCY_REVERT}
    assert v14.repositories == v13.repositories
    assert v14.risks == v13.risks
    for repository in v14.repositories:
        assert v14.acceptance_criteria[repository] is v13.acceptance_criteria[repository]
        assert v14.rollback_plans[repository] is v13.rollback_plans[repository]

    # The bump's conditions on the act are version 13's, field for field.
    old, new = v13.landing, v14.landing
    assert new.update_types == old.update_types
    assert new.require_head_current_with_base == old.require_head_current_with_base
    assert new.excluded_ecosystems == old.excluded_ecosystems
    assert new.rollout_workflows == old.rollout_workflows
    assert old.revert_landing is None

    # The inert lane is version 13's, unchanged.
    assert v13.inert_landing is not None and v14.inert_landing is not None
    for name in (
        "repositories",
        "permitted_authors",
        "excluded_ecosystems",
        "require_head_current_with_base",
        "non_ecosystem_authors",
    ):
        assert getattr(v14.inert_landing, name) == getattr(v13.inert_landing, name), name
    assert not v14.inert_landing.repositories & v14.repositories


def test_the_revert_lands_without_pace_or_window_and_only_from_the_dispatch_app():
    revert = current().landing.revert_landing
    assert revert is not None
    assert revert.change_class == DEPENDENCY_REVERT
    assert revert.permitted_authors == frozenset({DISPATCH_APP})
    assert revert.exempt_from_pace is True
    assert revert.exempt_from_change_window is True


def test_the_revert_remedy_restores_the_bump_for_every_repository():
    """A remedy for every repository the policy names, and it is not the bump's remedy: undoing a
    revert is re-pointing at the reverted merge's image and reverting the revert."""
    policy = current()
    plans = policy.class_rollback_plans[DEPENDENCY_REVERT]
    assert set(plans) == set(policy.repositories)
    for repository, plan in plans.items():
        assert plan != policy.rollback_plans[repository]
        assert plan.target == "image"
        assert any("revert this revert" in step for step in plan.steps)
        assert any("re-point" in step for step in plan.steps)


def test_only_the_revert_class_has_a_remedy_of_its_own():
    assert set(current().class_rollback_plans) == {DEPENDENCY_REVERT}


@pytest.mark.parametrize("repository", [CHANGE_MANAGER, BRAIN])
def test_a_revert_proposal_conforms_and_is_approved_by_the_server(client, m2m, repository):
    body = client.post(
        "/api/deploy-changes", json=revert_conformant(repository), headers=m2m
    ).json()
    assert body["status"] == "approved"
    assert body["policy_objections"] == []
    assert body["policy_version"] == CURRENT_VERSION


def test_a_revert_carrying_the_bumps_remedy_is_refused():
    """The remedy is chosen by the class: a revert whose rollback is "revert the merge" would put
    the bad bump back on the default branch by way of its own remedy."""
    policy = current()
    row = _Row(**revert_conformant(rollback_plan=policy.rollback_plans[CHANGE_MANAGER].as_stored()))
    assert objections(policy, row) == ("rollback_plan_not_ratified",)


def test_a_bump_carrying_the_reverts_remedy_is_refused():
    policy = current()
    row = _Row(**revert_conformant(change_class=BUMP))
    assert objections(policy, row) == ("rollback_plan_not_ratified",)


def test_a_revert_is_held_to_its_repositorys_criteria():
    policy = current()
    row = _Row(**revert_conformant(acceptance_criteria=["something nobody ratified"]))
    assert objections(policy, row) == ("acceptance_criteria_not_ratified",)


def test_a_revert_for_a_repository_outside_the_policy_is_refused():
    row = _Row(**revert_conformant(target_repository="alobarquest/orchestrator"))
    assert objections(current(), row) == ("repository_not_in_policy",)


def test_version_thirteen_refuses_the_revert_class():
    """The control on the grant: before version 14 this record was not policy's to approve."""
    thirteen = policy_for(13)
    assert thirteen is not None
    bump_remedy = thirteen.rollback_plans[CHANGE_MANAGER].as_stored()
    row = _Row(**revert_conformant(rollback_plan=bump_remedy))
    assert objections(thirteen, row) == ("change_class_not_in_policy",)


@pytest.mark.parametrize("version", sorted(v for v in REGISTRY if v < 14))
def test_a_version_that_declares_no_revert_landing_OMITS_the_key(version):
    """Versions 1 to 13 serve the bytes they always served."""
    policy = REGISTRY[version]
    assert policy.landing.revert_landing is None
    assert not policy.class_rollback_plans
    assert "revert_landing" not in landing_conditions_dict(policy)


def test_the_served_conditions_carry_the_revert_landing(client, m2m):
    served = client.get("/api/landing-policy", headers=m2m).json()["landing"]["revert_landing"]
    assert served == {
        "change_class": DEPENDENCY_REVERT,
        "permitted_authors": [DISPATCH_APP],
        "exempt_from_pace": True,
        "exempt_from_change_window": True,
    }


def test_the_record_row_carries_the_revert_landing(client, m2m):
    """The orchestrator reads the conditions where it reads the record."""
    item = client.post("/api/deploy-changes", json=revert_conformant(), headers=m2m).json()
    assert item["landing_conditions"]["revert_landing"]["change_class"] == DEPENDENCY_REVERT
