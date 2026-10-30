"""Policy approval of standing `work` records: dependency updates and credential rotations.

Dependency updates arrived with the bridge layer (Part 3); rotations with the orchestrator's
ADR-0055 amendment 16.

A `work` record is approved by a person, and `work` is deliberately outside
`POLICY_APPROVED_SOURCES`: that set refuses human approval to every caller, so a source-wide
policy would make rotation and app-change records unapprovable by anyone. This policy is per
RECORD instead. A record that conforms is approved inside its own proposal transaction; one
that does not stays `pending` and a person decides it exactly as before.

A rotation record (class `credential-rotation`, package `rotation-<credential>`) names no
repository, so it conforms on its own shape and the deploy policy plays no part. Approving it grants
nothing the package revision did not: the carrier carries a record only when its package revision is
approved, with the approval's hash verified against the tamper-evident chain, and intent-packages
refuses policy approval of the rotation profile, so only a named person approves a rotation
revision. That approval is the rotation's one click; this record restates it.

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

import re
from typing import Final

from app.deploy_policy import current
from app.models import ChangeItem

WORK_POLICY_ACTOR: Final = "work-policy"

DEPENDENCY_UPDATE: Final = "dependency-update"
# The orchestrator rotation proposer's class; its carrier refuses it on any package whose profile
# isn't the rotation profile.
CREDENTIAL_ROTATION: Final = "credential-rotation"
PACKAGES_REPOSITORY: Final = "AlobarQuest/intent-packages"
POLICY_RISK: Final = "caution"
# intent-packages' standing rotation package ids, `rotation-<credential id>`.
ROTATION_PACKAGE: Final = re.compile(r"rotation-[a-z0-9][a-z0-9-]*")


def is_rotation(item: ChangeItem) -> bool:
    """Whether the record claims to be a credential rotation, judged by the rotation rules."""
    return item.change_class == CREDENTIAL_ROTATION


def objections(item: ChangeItem) -> list[str]:
    """Why this record is not a standing package this policy approves.

    Empty means it conforms. The names are stable strings a test can pin.
    """
    found: list[str] = []
    if (item.package_source_repository or "").lower() != PACKAGES_REPOSITORY.lower():
        found.append("package_source_not_intent_packages")
    if item.risk != POLICY_RISK:
        found.append("risk_not_caution")
    return found + (_rotation(item) if is_rotation(item) else _dependency_update(item))


def _rotation(item: ChangeItem) -> list[str]:
    found: list[str] = []
    if not ROTATION_PACKAGE.fullmatch(item.package_id or ""):
        found.append("package_not_a_rotation_package")
    if item.target_repository is not None:
        found.append("rotation_names_a_target_repository")
    return found


def _dependency_update(item: ChangeItem) -> list[str]:
    found: list[str] = []
    if item.change_class != DEPENDENCY_UPDATE:
        found.append("change_class_not_dependency_update")
    policy = current()
    inert = policy.inert_landing.repositories if policy.inert_landing else frozenset()
    repository = (item.target_repository or "").lower()
    if repository not in inert | policy.repositories:
        found.append("target_repository_not_in_policy")
    return found
