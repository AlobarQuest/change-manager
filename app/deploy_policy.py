"""What a human has pre-approved for a deploying merge, as pinned versioned data.

ADR-0019 increment 5. Devon's ruling, 2026-08-10: *"It needs human approval, but that approval
comes in the form of policy and process. Not individual action approvals. Performing the change in
the designated change window, under the designated criteria, IS human approval, if a human was in
charge of setting those parameters."*

This module is those parameters. A deploy record whose shape conforms to the current version is
approved by the server at proposal -- no route grants it, no caller chooses it, conformance decides.

WHY DATA-IN-CODE RATHER THAN A TOML ARTIFACT. This service loads no artifact today: `app/` imports
neither `tomllib` nor `pathlib`, and the image copies only `app/`, `alembic/`, `alembic.ini` and
`entrypoint.sh`. A file would need a COPY line, a loader, and a "document that does not load
permits nothing" path -- new failure surface for something that can only ever change by a
deliberate commit anyway. The estate's own exemplar for pinned, versioned, re-evaluable policy is
`landing_ledger/rules.py`, which is a Python registry. This follows it.

THE EDITING CONTRACT, in ADR-0010's terms. A new field is an additive version bump made ONLY in the
same commit that ships the code reading it. **A superseded version is retained verbatim and is
never edited** -- a record approved under it stores its number, and re-evaluating that approval
years later means looking the old version up and finding what it actually said. Editing version 1
in place would silently change what every past approval meant, which is the failure `rules.py`
exists to prevent.

WHAT THIS CONSTRAINS, AND WHAT IT DELIBERATELY CANNOT. Every term below is a fact this service holds
or a human pinned. **This service has no GitHub egress and cannot attest a caller**, so a term over
caller-declared GitHub facts would be policy resting on something it cannot check -- the fail-open
ADR-0019 increment 3 killed. Facts about the change itself are therefore NOT decided here; they are
declared in `LANDING_CONDITIONS` and enforced by the party that can read GitHub, at the moment of
the act. Adversarial review of increment 5 put this sharply: not one term below is a function of the
CHANGE. `change_class` and `risk` are literals the producer writes about every pull request it sees,
and the rest are functions of the repository. What a conformant record attests is therefore precise
and narrow -- **a human pinned this repository, these criteria and this remedy** -- and every
change-specific question is left to the landing terms on purpose.

THE SECOND COPY IS DELIBERATE AND ITS DISAGREEMENT IS THE POINT. `acceptance_criteria` below is a
second copy of what the orchestrator's producer derives from the rollout workflow's bytes. When that
workflow changes, the producer derives something different, the two stop matching, and the record
stops being approved until a human reads what changed and bumps the version. That is the only thing
in this estate that notices a rollout workflow change. It looks like the vocabulary-mismatch defect
this estate documents and it is its inverse: it fails closed in both directions, and the copy exists
so a change on one side must be ratified against the other.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

# Update types a landing may carry, in Dependabot's own vocabulary. DECLARED HERE, ENFORCED AT THE
# LANDING, for the reason in the module docstring: the version delta lives in GitHub and this
# service cannot read it.
SEMVER_PATCH: Final = "semver-patch"
SEMVER_MINOR: Final = "semver-minor"
SEMVER_MAJOR: Final = "semver-major"


@dataclass(frozen=True)
class LandingConditions:
    """Conditions on the ACT, which this service declares and does not evaluate.

    Served on `GET /api/deploy-policy` so the orchestrator reads them rather than holding a second
    copy -- one holder, one reader. Increment 3 established that a policy value copied into a second
    service is a fail-open, and the shape here is the same one `GET /api/v1/factory-policy` already
    uses in the other direction.
    """

    update_types: frozenset[str]
    require_head_current_with_base: bool
    rationale: str


@dataclass(frozen=True)
class Rollback:
    steps: tuple[str, ...]
    target: str

    def as_stored(self) -> dict:
        """The shape a proposal carries, so conformance compares like with like."""
        return {"steps": list(self.steps), "target": self.target}


@dataclass(frozen=True)
class DeployPolicy:
    version: int
    decided: str
    rationale: str
    repositories: frozenset[str]
    change_classes: frozenset[str]
    risks: frozenset[str]
    acceptance_criteria: Mapping[str, tuple[str, ...]]
    rollback_plans: Mapping[str, Rollback]
    landing: LandingConditions


# ---------------------------------------------------------------------------
# Version 1 -- Devon, 2026-08-11.
# ---------------------------------------------------------------------------

_V1_CHANGE_MANAGER_CRITERIA: Final = (
    "the rollout runs for this merge on alobarquest/change-manager, and its production step "
    "concludes success (job 'build-and-deploy', step 'Trigger Coolify redeploy')",
    "production answered /api/health reporting the merged commit as its revision within 600 "
    "seconds",
)

_V1_CHANGE_MANAGER_ROLLBACK: Final = Rollback(
    steps=(
        "re-point the moving image tag at the previous per-SHA tag and redeploy",
        "revert the merge commit on main, so main and production agree again",
    ),
    target="image",
)

_V1_LANDING: Final = LandingConditions(
    update_types=frozenset({SEMVER_PATCH, SEMVER_MINOR}),
    require_head_current_with_base=True,
    rationale=(
        "Patch and minor only, which is STRICTER than the cascade governing the repositories "
        "where landing changes nothing already serving -- that cascade permits a major update to "
        "the workflow-automation ecosystem, on the premise that the required check gating it IS "
        "the thing being bumped, so passing it means the new version has been exercised exactly "
        "as it will be used. That premise fails here: the rollout job does not run on a pull "
        "request, only on a landing, so such a bump would be exercised for the first time during "
        "the very rollout it is supposed to gate. Excluding it follows the cascade's own "
        "reasoning rather than departing from it. "
        "A requirement-RANGE bump carries no update type at all and is therefore refused for want "
        "of a parseable delta -- the same answer the other lane reaches by a different route. "
        "THAT IS THE INTENDED BEHAVIOUR AND NOT A PARSER DEFECT; do not 'fix' it. "
        "The freshness condition is here rather than in branch protection deliberately: making "
        "the branch strict would serialise human merges too and applies estate-wide behaviour "
        "nobody versions, where a policy condition is evaluated at landing, lives in the artifact "
        "a human edits, and produces a named refusal rather than a silent block."
    ),
)

V1: Final = DeployPolicy(
    version=1,
    decided="2026-08-11",
    rationale=(
        "One repository, because its rollout proves what the record claims. Landing on "
        "alobarquest/change-manager is followed by a poll of /api/health until it reports the "
        "merged commit, so a green rollout genuinely establishes that production is serving the "
        "change. The other repository where landing redeploys attests only that a domain answered "
        "within thirty seconds of a webhook, which its own registry records as unable to confirm "
        "the merged build is live -- and the rollout watcher reads the same workflow conclusion, "
        "so it inherits that blind spot rather than compensating for it. There is no second net "
        "there. Landing unattended under criteria documented as unable to detect the failure is "
        "not accepting that risk, it is defeating it. That repository joins by a one-line bump of "
        "this policy once its rollout verifies the revision, which is the improvement this "
        "repository already made to its own workflow."
    ),
    repositories=frozenset({"alobarquest/change-manager"}),
    change_classes=frozenset({"dependency-update"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={"alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA},
    rollback_plans={"alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK},
    landing=_V1_LANDING,
)

# Every version ever, retained. A record stores the number that approved it, so an approval stays
# re-evaluable after the policy has moved on.
REGISTRY: Final[dict[int, DeployPolicy]] = {policy.version: policy for policy in (V1,)}

CURRENT_VERSION: Final = 1


def policy_for(version: int) -> DeployPolicy | None:
    """The version a record was approved under, or None if this build does not know it.

    None is a finding for the caller, never a skip: a record naming a version this build cannot
    produce is a record whose approval cannot be re-derived.
    """
    return REGISTRY.get(version)


def current() -> DeployPolicy:
    return REGISTRY[CURRENT_VERSION]


def objections(policy: DeployPolicy, item: object) -> tuple[str, ...]:
    """Why this record does not conform. Empty means it does.

    Fail closed on every shape that is not what it should be: a missing repository, criteria that
    are not a list of strings, a rollback plan that is not the pinned mapping. An unreadable field
    is an objection, never a skip -- the whole value of this function is that the only way through
    it is to be exactly what a human pinned.
    """
    repository = getattr(item, "target_repository", None)
    if not isinstance(repository, str) or not repository:
        return ("target_repository_unreadable",)
    key = repository.lower()
    if key not in policy.repositories:
        return ("repository_not_in_policy",)

    found: list[str] = []
    if getattr(item, "change_class", None) not in policy.change_classes:
        found.append("change_class_not_in_policy")
    if getattr(item, "risk", None) not in policy.risks:
        found.append("risk_not_in_policy")

    criteria = getattr(item, "acceptance_criteria", None)
    if not isinstance(criteria, list) or tuple(criteria) != policy.acceptance_criteria[key]:
        # The load-bearing term. A mismatch means what a green rollout attests has moved since a
        # human ratified it, so the remedy attached to those criteria may no longer be the right
        # remedy.
        found.append("acceptance_criteria_not_ratified")

    rollback = getattr(item, "rollback_plan", None)
    if rollback != policy.rollback_plans[key].as_stored():
        found.append("rollback_plan_not_ratified")

    return tuple(found)


def landing_conditions_dict(policy: DeployPolicy) -> dict:
    """The conditions on the act, in the shape the landing party reads them."""
    return {
        "update_types": sorted(policy.landing.update_types),
        "require_head_current_with_base": policy.landing.require_head_current_with_base,
        "rationale": policy.landing.rationale,
    }
