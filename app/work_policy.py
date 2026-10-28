"""Policy approval of standing dependency-update `work` records (bridge layer, Part 3).

A `work` record is approved by a person, and `work` is deliberately outside
`POLICY_APPROVED_SOURCES`: that set refuses human approval to every caller, so a source-wide
policy would make rotation and app-change records unapprovable by anyone. This policy is per
RECORD instead. A record that conforms is approved inside its own proposal transaction; one
that does not stays `pending` and a person decides it exactly as before.

It approves and nothing else. It never revokes, never touches a record a person has decided,
and never runs on a record that is not `pending`.

The inert population is read from the current deploy policy (`inert_landing.repositories`),
never copied: a repository that starts to deploy leaves that list, and its bumps stop being
approved here in the same release.
"""

from typing import Final

from app.deploy_policy import current
from app.models import ChangeItem

WORK_POLICY_ACTOR: Final = "work-policy"

DEPENDENCY_UPDATE: Final = "dependency-update"
PACKAGES_REPOSITORY: Final = "AlobarQuest/intent-packages"
POLICY_RISK: Final = "caution"


def objections(item: ChangeItem) -> list[str]:
    """Why this record is not a standing dependency-update package for an inert repository.

    Empty means it conforms. The names are stable strings a test can pin.
    """
    found: list[str] = []
    if item.change_class != DEPENDENCY_UPDATE:
        found.append("change_class_not_dependency_update")
    inert = current().inert_landing
    repository = (item.target_repository or "").lower()
    if inert is None or repository not in inert.repositories:
        found.append("target_repository_not_inert")
    if (item.package_source_repository or "").lower() != PACKAGES_REPOSITORY.lower():
        found.append("package_source_not_intent_packages")
    if item.risk != POLICY_RISK:
        found.append("risk_not_caution")
    return found
