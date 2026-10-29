"""Policy approval of standing dependency-update `work` records (bridge layer, Part 3).

A `work` record is approved by a person, and `work` is deliberately outside
`POLICY_APPROVED_SOURCES`: that set refuses human approval to every caller, so a source-wide
policy would make rotation and app-change records unapprovable by anyone. This policy is per
RECORD instead. A record that conforms is approved inside its own proposal transaction; one
that does not stays `pending` and a person decides it exactly as before.

It approves and nothing else. It never revokes, never touches a record a person has decided,
and never runs on a record that is not `pending`.

Reactivating a `wontfix` record returns it to `pending`, which this policy then acts on, so a
conforming replay approves it. That is a choice: `defer` is how a person holds a record.

The population is read from the current deploy policy, never copied: the deploying
repositories (`repositories`) and the inert ones (`inert_landing.repositories`). A repository
that leaves both stops being approved here in the same release. The two lists are disjoint, which
`test_current_policy_landing_populations_are_disjoint` holds
(for the current version).
"""

from typing import Final

from app.deploy_policy import current
from app.models import ChangeItem

WORK_POLICY_ACTOR: Final = "work-policy"

DEPENDENCY_UPDATE: Final = "dependency-update"
PACKAGES_REPOSITORY: Final = "AlobarQuest/intent-packages"
POLICY_RISK: Final = "caution"


def objections(item: ChangeItem) -> list[str]:
    """Why this record is not a standing dependency-update package for a repository in policy.

    Empty means it conforms. The names are stable strings a test can pin.
    """
    found: list[str] = []
    if item.change_class != DEPENDENCY_UPDATE:
        found.append("change_class_not_dependency_update")
    policy = current()
    inert = policy.inert_landing.repositories if policy.inert_landing else frozenset()
    repository = (item.target_repository or "").lower()
    if repository not in inert | policy.repositories:
        found.append("target_repository_not_in_policy")
    if (item.package_source_repository or "").lower() != PACKAGES_REPOSITORY.lower():
        found.append("package_source_not_intent_packages")
    if item.risk != POLICY_RISK:
        found.append("risk_not_caution")
    return found
