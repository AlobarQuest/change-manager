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
from dataclasses import dataclass, field
from typing import Final

# Update types a landing may carry, in Dependabot's own vocabulary. DECLARED HERE, ENFORCED AT THE
# LANDING, for the reason in the module docstring: the version delta lives in GitHub and this
# service cannot read it.
SEMVER_PATCH: Final = "semver-patch"
SEMVER_MINOR: Final = "semver-minor"
SEMVER_MAJOR: Final = "semver-major"

# The workflow-automation ecosystem, spelled as the update bot spells it in a branch name, which
# is where the landing party reads it. WITH AN UNDERSCORE, and that is not a detail: the estate's
# landing ledger records a revision of the other lane's gate that compared the hyphenated form
# against this value, matched nothing, and therefore permitted nothing while reading as though it
# permitted more. That defect is transcribed rather than corrected there, so that it stays
# visible; here the correct spelling is pinned by a test.
GITHUB_ACTIONS: Final = "github_actions"


@dataclass(frozen=True)
class WorkflowPin:
    """WHICH BYTES a repository's rollout workflow must still be, for a landing to proceed.

    A POINTER, never a transcription. `acceptance_criteria` above says what a green rollout
    attests; this says which file, at which blob, that statement was made about. The landing party
    reads the blob at the trigger branch's head and refuses when it differs -- so a rollout
    workflow that changes stops every unattended landing until a human reads what changed and
    ratifies it by bumping this policy.

    A pin rather than a copy for the reason the estate's landing ledger pins its own gate: the
    only thing that can classify a workflow's bytes is a human, that classification lives in one
    place, and a second reader would need a second copy of it. A blob sha needs neither.

    Named as the FILE PATH and the BLOB, because the two answer different failures: a renamed path
    reads as an absent file, which must refuse rather than pass, and an edited file at the same
    path reads as a different blob.
    """

    path: str
    blob_sha: str


@dataclass(frozen=True)
class LandingConditions:
    """Conditions on the ACT, which this service declares and does not evaluate.

    Served on `GET /api/deploy-policy` so the orchestrator reads them rather than holding a second
    copy -- one holder, one reader. Increment 3 established that a policy value copied into a second
    service is a fail-open, and the shape here is the same one `GET /api/v1/factory-policy` already
    uses in the other direction.

    `rollout_workflows` DEFAULTS TO EMPTY so that version 1, which predates it, is retained
    verbatim rather than edited -- the editing contract in this module's header. A version that
    declares no pin for a repository is not a version that waives the condition: the landing party
    fails closed on a repository it has no pin for, because "nobody said which bytes" and "these
    bytes are fine" are not the same statement.
    """

    update_types: frozenset[str]
    require_head_current_with_base: bool
    rationale: str
    rollout_workflows: Mapping[str, WorkflowPin] = field(default_factory=dict)
    # ADR-0036. WHICH RULE A VERSION DECIDES BY, carried as the presence of this field.
    #
    # `None` -- every version before the fifth -- means the version decides by `update_types`.
    # A frozenset means it decides on the OUTCOME: a bump whose required checks pass may land
    # whatever its version delta or absence of one, EXCEPT in the ecosystems named here, which are
    # the ones those checks do not exercise. It defaults to `None` for the same reason
    # `rollout_workflows` defaults to empty -- so the dataclass can gain a field while every
    # superseded version above stays readable exactly as it was decided.
    #
    # THIS SERVICE STILL EVALUATES NOTHING. Like every other term here, the ecosystem lives in
    # GitHub -- it is the second segment of the branch the update bot opens -- and the landing
    # party is the one that can read it.
    excluded_ecosystems: frozenset[str] | None = None


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

# ---------------------------------------------------------------------------
# Version 2 -- Devon, 2026-08-12. Version 1 above is retained verbatim.
# ---------------------------------------------------------------------------
#
# ADDS ONE CONDITION AND CHANGES NOTHING ELSE: the rollout workflow a landing rests on must still
# be the bytes this version was written about. Everything a version-1 record satisfied it still
# satisfies, so a record approved under version 1 conforms to version 2 on shape -- and is
# nevertheless refused at the landing until it is re-approved, because the landing binds an
# approval to the CURRENT version. That is the narrowing taking effect at the act, which is the
# only mechanism by which moving this file binds an approval that already exists.

_V2_LANDING: Final = LandingConditions(
    update_types=frozenset({SEMVER_PATCH, SEMVER_MINOR}),
    require_head_current_with_base=True,
    rationale=(
        "Patch and minor only, which is STRICTER than the cascade governing the repositories "
        "where landing changes nothing already serving, for the reason version 1 gives: the "
        "rollout job does not run on a pull request, only on a landing, so a major bump to the "
        "workflow-automation ecosystem would be exercised for the first time during the very "
        "rollout it is supposed to gate. A requirement-RANGE bump carries no update type at all "
        "and is refused for want of a parseable delta. THAT IS THE INTENDED BEHAVIOUR AND NOT A "
        "PARSER DEFECT; do not 'fix' it. Freshness is a policy condition rather than a strict "
        "branch, because a strict branch serialises human merges too and applies estate-wide "
        "behaviour nobody versions. "
        "WHAT VERSION 2 ADDS IS THE ROLLOUT-WORKFLOW PIN. The acceptance criteria say what a "
        "green rollout attests, and until now nothing checked that the workflow producing it was "
        "still the bytes that statement was made about. The producer notices a moved workflow on "
        "its next pass and revokes the approval -- but that is a scheduled job rather than a "
        "condition on the act, so between a workflow landing and the next pass a change could be "
        "landed under criteria describing bytes that no longer exist. The pin closes it at the "
        "act: the landing party reads the blob at the trigger branch's head and refuses on any "
        "difference, so a rollout workflow that changes stops unattended landing until a human "
        "reads the change and bumps this policy. It is the discipline the estate's landing ledger "
        "already applies to the gate workflow it re-evaluates rule landings against."
    ),
    rollout_workflows={
        "alobarquest/change-manager": WorkflowPin(
            path=".github/workflows/deploy.yml",
            # `191ec5a`, 2026-08-07 -- the revision that polls /api/health until it reports the
            # merged commit. It is what the acceptance criteria describe, and the only revision of
            # this workflow under which a green rollout means what they say.
            blob_sha="a47d4b187c93971a5b5915ce87a963bd4ef35e30",
        )
    },
)

# The criteria and the remedy are UNCHANGED between the two versions, so they are the same
# constants rather than a second transcription of one judgment. The `_V1_` names record where each
# was introduced; a version that changes one declares its own.
V2: Final = DeployPolicy(
    version=2,
    decided="2026-08-12",
    rationale=(
        "One repository, unchanged from version 1 and for its reasons: landing on "
        "alobarquest/change-manager is followed by a poll of /api/health until it reports the "
        "merged commit, so a green rollout genuinely establishes that production is serving the "
        "change, where the other repository where landing redeploys attests only that a domain "
        "answered. What this version changes is that the workflow making that attestation is now "
        "pinned by its bytes, so the claim cannot quietly stop being true of the thing that runs."
    ),
    repositories=frozenset({"alobarquest/change-manager"}),
    change_classes=frozenset({"dependency-update"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={"alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA},
    rollback_plans={"alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK},
    landing=_V2_LANDING,
)

# ---------------------------------------------------------------------------
# Version 3 -- Devon, 2026-08-15. Versions 1 and 2 above are retained verbatim.
# ---------------------------------------------------------------------------
#
# ADDS A SECOND REPOSITORY AND CHANGES NOTHING ELSE. `alobarquest/brain` joins on the condition
# version 1 named for it: "that repository joins by a one-line bump of this policy once its
# rollout verifies the revision". That shipped 2026-08-14 as brain#47 (merge `1d9e7d38`) and is
# pinned below by the bytes that make it. Every term `change-manager` relied on is unchanged and
# reuses the same constants, so this is additive for it -- and it is nevertheless refused at the
# landing until re-approved, because the landing binds an approval to the CURRENT version. That
# is version 2's narrowing-at-the-act mechanism, and it costs nothing here: the only approved
# record when this was written is a requirement-range bump that no version can land.

# WHAT A `brain` APPROVAL ATTESTS -- BYTE-IDENTICAL TO WHAT THE PRODUCER DERIVES, which is the
# constraint that decides the wording rather than a preference. The orchestrator's transcription
# of `c5c0887` is the other copy of this judgment (`deploy_watcher/workflows.py`), and
# `objections` below compares the two literally: they drift, and every `brain` record objects
# `acceptance_criteria_not_ratified` forever with nothing saying which side moved.
#
# AND IT IS DELIBERATELY NOT "ALL FOUR APPLICATIONS". brain's rollout triggers four Coolify
# applications from one image and skips any whose UUID secret is unset, in the trigger loop and
# in the verification loop alike. All four are configured today and all four reported the merged
# revision on that workflow's first live run, so "all four" would be true of today -- and it is
# refused on three grounds. The criteria transcribe what a rollout's BYTES attest, and no pin
# over bytes can read a secret's value, so the strong form would be a transcription that lies.
# A record whose criteria say four when three ran would describe something that did not happen,
# in the one field a later reader holds the deploy to. And it would not buy the property it is
# wanted for: removing a secret moves no bytes, so the pin does not fire, the rollout stays
# green, and the criteria would quietly overstate a passing run rather than refuse it.
#
# So the ceiling is RECORDED rather than closed, and the record says where it is. A rollout that
# triggered NONE now fails -- that was the one path through the step that could not fail, and
# brain#47 closed it -- so an empty deploy cannot pass. Three of four still can. Making "all
# four" true means brain's workflow refusing an unset secret, which is a byte change, hence a
# new pin, a new transcription and a new version of this policy. That is the right cost for
# changing how many applications a human is pre-approving a deploy of.
_V3_BRAIN_CRITERIA: Final = (
    "the rollout runs for this merge on alobarquest/brain, and its production step concludes "
    "success (job 'deploy', step 'Deploy brain apps')",
    "every brain application this rollout triggered answered /api/health reporting the merged "
    "commit as its revision and a status of ok, within 600 seconds; an application whose Coolify "
    "UUID secret is unset is neither triggered nor checked, and a rollout that triggered none "
    "fails rather than passing empty",
)

# `each affected app's`, where change-manager's says `the moving image tag`, and the difference is
# the whole of brain: four applications pull one image, so putting production back is four
# operations and any of them can fail on its own. A rollback that reaches three leaves the four
# split across images -- a state no acceptance criterion describes and no run reports, because the
# rollout that would have checked them is not the thing being run. Reverting the merge is
# therefore not the tidy second step it is for change-manager; it is what makes the four agree
# again whichever way the first step went.
#
# `image` rather than `commit` is not a preference either: brain builds from requirements.txt with
# no lockfile, so rebuilding the same commit can resolve a different dependency set, and rolling
# back to a commit would be rolling forward into an untested one.
#
# AND THIS IS BYTE-COMPARED TOO, so the wording has no more latitude than the criteria above: the
# producer's copy is `change_proposer.criteria._ROLLBACKS`, and improving the remedy on one side
# alone stops every brain record conforming. The caveat about a partial rollback belongs here, in a
# comment, rather than in a step -- prose that has to match another repository byte for byte is the
# wrong place to record a judgement nobody can act on from the record anyway.
_V3_BRAIN_ROLLBACK: Final = Rollback(
    steps=(
        "re-point each affected app's moving image tag at the previous per-SHA tag and redeploy",
        "revert the merge commit on main, so main and production agree again",
    ),
    target="image",
)

_V3_LANDING: Final = LandingConditions(
    update_types=frozenset({SEMVER_PATCH, SEMVER_MINOR}),
    require_head_current_with_base=True,
    rationale=(
        "Patch and minor only, which is STRICTER than the cascade governing the repositories "
        "where landing changes nothing already serving, for the reason version 1 gives: the "
        "rollout job does not run on a pull request, only on a landing, so a major bump to the "
        "workflow-automation ecosystem would be exercised for the first time during the very "
        "rollout it is supposed to gate. That holds for both repositories this version admits -- "
        "brain's deploy job is gated on a push to main and fires on nothing else. A requirement-"
        "RANGE bump carries no update type at all and is refused for want of a parseable delta. "
        "THAT IS THE INTENDED BEHAVIOUR AND NOT A PARSER DEFECT; do not 'fix' it. Freshness is a "
        "policy condition rather than a strict branch, because a strict branch serialises human "
        "merges too and applies estate-wide behaviour nobody versions. "
        "WHAT VERSION 3 ADDS IS A SECOND PINNED ROLLOUT, not a second kind of condition. The pin "
        "version 2 introduced is what makes a repository's acceptance criteria describe bytes "
        "that still exist, so admitting a repository without one would admit criteria nobody "
        "could hold to the thing that runs. brain's rollout is pinned at `.github/workflows/"
        "ci.yml` -- it has no deploy.yml, its deploy job lives in the CI workflow, and its "
        "revision poll was deliberately kept inline in that file rather than moved to a script "
        "so that these bytes cover it."
    ),
    rollout_workflows={
        "alobarquest/change-manager": WorkflowPin(
            path=".github/workflows/deploy.yml",
            # `191ec5a`, 2026-08-07 -- unchanged from version 2, and the same constant is not
            # reused only because a version declares its own pins rather than borrowing a
            # superseded version's mapping.
            blob_sha="a47d4b187c93971a5b5915ce87a963bd4ef35e30",
        ),
        "alobarquest/brain": WorkflowPin(
            path=".github/workflows/ci.yml",
            # `1d9e7d38`, 2026-08-14 -- the revision that replaces the liveness poll with a
            # revision poll, against an image built with GIT_SHA and an /api/health that reports
            # it. Read from brain's `main` on 2026-08-15 rather than transcribed from a handoff:
            # it is the only revision of this workflow under which a green run means what the
            # criteria above say.
            blob_sha="c5c088719cd340f0071b875c6a82439292ed8756",
        ),
    },
)

# change-manager's criteria and remedy are UNCHANGED from version 1, so they are the same
# constants rather than a third transcription of one judgment.
V3: Final = DeployPolicy(
    version=3,
    decided="2026-08-15",
    rationale=(
        "Two repositories. alobarquest/brain joins on the condition version 1 named for it: its "
        "rollout now waits until every application it deployed reports the merged commit as its "
        "revision, so a green run establishes that production is serving the change rather than "
        "that a domain answered. Until 2026-08-14 it attested only the latter, and landing "
        "unattended under criteria documented as unable to detect the failure is not accepting "
        "that risk but defeating it. The evidence for widening is three consecutive autonomous "
        "landings on alobarquest/change-manager, each confirmed against production and each "
        "settled by the rollout watcher with no human acting. "
        "What a brain approval attests is narrower than 'all four applications', deliberately, "
        "and the reasoning is recorded above its criteria: the criteria transcribe what the "
        "rollout's bytes attest, the bytes skip an application whose Coolify secret is unset, "
        "and a stronger claim would overstate a passing run without being able to refuse one. "
        "A rollout that triggers nothing now fails; three of four still passes, and that ceiling "
        "is stated in the record rather than closed here. Nothing about change-manager changes."
    ),
    repositories=frozenset({"alobarquest/change-manager", "alobarquest/brain"}),
    change_classes=frozenset({"dependency-update"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA,
        "alobarquest/brain": _V3_BRAIN_CRITERIA,
    },
    rollback_plans={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK,
        "alobarquest/brain": _V3_BRAIN_ROLLBACK,
    },
    landing=_V3_LANDING,
)

# ---------------------------------------------------------------------------
# Version 4 -- Devon, 2026-08-25. Versions 1, 2 and 3 above are retained verbatim.
# ---------------------------------------------------------------------------
#
# ADMITS A SECOND CHANGE CLASS AND CHANGES NOTHING ELSE. `factory-delivery` is the class the
# orchestrator's producer writes on a record for a pull request the FACTORY opened, as distinct
# from an update bot's. ADR-0025, decided 2026-08-17: *"A change record for a factory-opened pull
# request is approved by conformance to that policy, as a Dependabot record already is. There is
# no per-record human approval."* Every repository, criterion, remedy, pin and landing condition
# is the same object version 3 declared, so this is additive for `dependency-update` -- and a
# record approved under version 3 is nevertheless refused at the landing until it is re-approved,
# because the landing binds an approval to the CURRENT version. That is version 2's
# narrowing-at-the-act mechanism, unchanged, and the producer's next pass re-stamps every record
# that still conforms.
#
# WHY A CLASS GRANT IS THE RIGHT SHAPE FOR THIS, which is the part a later reader will want.
# A per-record human approval was considered and rejected, and the decisive argument is structural
# rather than a matter of taste: THIS SERVICE HAS NO GITHUB EGRESS. A record approval therefore
# *cannot* show a human what changed -- not "does not today", but cannot, which is the same
# property the module docstring above gives for leaving every change-specific term to the landing
# party. What the form could show was measured on the three records that landed (items 51, 52 and
# 53, three different bumps): the acceptance criteria and the rollback plan are byte-identical
# across all three, so its only moving field is a pull request number. An approval on those terms
# is not a review of the change; it is a re-ratification of the repository's deployment terms,
# which a human ratified once when this file was written. A control that is structurally
# uninformative gets clicked through, the same way a permanently-red signal stops being read.
#
# WHAT IS GIVEN UP, STATED PLAINLY: a person standing at the last gate. After this, nobody is
# prompted before a machine-authored change reaches production. The replacement is the
# human-judgment acceptance criterion on the intent package, and it is better placed rather than
# merely different -- a package whose work warrants reading carries one, which disqualifies its
# unit from the autonomous landing lane by construction, and a person merges it. That puts the
# human at the moment the diff exists. ADR-0025 records the risk that comes with it: the lever
# only works if it is used, and whether such a package must carry one is an authoring convention
# left open there deliberately, to be decided against a real factory record.
#
# THE CEILING THIS GRANT INHERITS, RECORDED RATHER THAN CLOSED. `acceptance_criteria` and
# `rollback_plans` are keyed by REPOSITORY while `change_classes` is a flat set, so
# `factory-delivery` necessarily inherits exactly the criteria `dependency-update` has for each
# repository. That is defensible -- both are statements about the deployment MECHANISM, equally
# true whatever changed -- but it means there is no way to require more verification of factory
# work than of a lockfile bump without keying criteria on `(repository, change_class)`. ADR-0025
# was decided with that correction in hand, and restructuring the keying is a separate decision
# with its own cost. It is not made here.

# change-manager's and brain's criteria, remedies and pins are UNCHANGED from version 3, so they
# are the same constants rather than a fourth transcription of two judgments. Only the landing
# rationale is version 4's own, for the reason version 3 gives: a version declares its own
# conditions rather than borrowing a superseded version's.
_V4_LANDING: Final = LandingConditions(
    update_types=frozenset({SEMVER_PATCH, SEMVER_MINOR}),
    require_head_current_with_base=True,
    rationale=(
        "Patch and minor only, which is STRICTER than the cascade governing the repositories "
        "where landing changes nothing already serving, for the reason version 1 gives: the "
        "rollout job does not run on a pull request, only on a landing, so a major bump to the "
        "workflow-automation ecosystem would be exercised for the first time during the very "
        "rollout it is supposed to gate. That holds for both repositories this version admits -- "
        "brain's deploy job is gated on a push to main and fires on nothing else. A requirement-"
        "RANGE bump carries no update type at all and is refused for want of a parseable delta. "
        "THAT IS THE INTENDED BEHAVIOUR AND NOT A PARSER DEFECT; do not 'fix' it. Freshness is a "
        "policy condition rather than a strict branch, because a strict branch serialises human "
        "merges too and applies estate-wide behaviour nobody versions. "
        "VERSION 4 ADDS NO CONDITION ON THE ACT AND REMOVES NONE, and the reason is worth stating "
        "because the version admits a class whose pull requests these terms were not written "
        "about. Both surviving terms are functions of the REPOSITORY and of the position of a "
        "branch, not of who authored the change, so neither becomes wrong when the author is the "
        "factory. But NEITHER IS A TERM ABOUT WHO AUTHORED IT, and that is the gap this version "
        "opens rather than closes. A factory pull request is meant to be landed by the lane that "
        "adjudicated the work behind it -- which asks whether the unit completed, whether its "
        "criteria were decided by the verifier from observed evidence, and whether an authority "
        "approval is bound to the envelope. NONE of those is asked by the lane these conditions "
        "govern, and that lane selects its subjects on approved status alone. So making a factory "
        "record approvable makes it VISIBLE to a lane that would land it on a weaker basis. What "
        "keeps such a record out today is an update type, which is read from a title stating a "
        "single version delta; a factory title usually states none -- but the pattern is only "
        "END-anchored, so a title ending 'from 0.15.20 to 0.16.2' parses, and a unit title is "
        "free text a human writes. A LANE SEPARATION THAT DEPENDS ON HOW SOMEBODY HAPPENED TO "
        "WORD A TITLE IS NOT A SEPARATION. The refusal belongs on the party that reads GitHub and "
        "selects the subject, keyed on the change class this version names, and it is tracked as "
        "the condition of this grant rather than assumed away here."
    ),
    rollout_workflows={
        "alobarquest/change-manager": WorkflowPin(
            path=".github/workflows/deploy.yml",
            # `191ec5a`, 2026-08-07 -- unchanged from versions 2 and 3.
            blob_sha="a47d4b187c93971a5b5915ce87a963bd4ef35e30",
        ),
        "alobarquest/brain": WorkflowPin(
            path=".github/workflows/ci.yml",
            # `1d9e7d38`, 2026-08-14 -- unchanged from version 3.
            blob_sha="c5c088719cd340f0071b875c6a82439292ed8756",
        ),
    },
)

V4: Final = DeployPolicy(
    version=4,
    decided="2026-08-25",
    rationale=(
        "Two repositories and two change classes. What version 4 grants is that a change record "
        "for a pull request the FACTORY opened -- change class 'factory-delivery' -- is approved "
        "by conformance to this policy, exactly as an update bot's record already is, with no "
        "per-record human approval. ADR-0025, decided 2026-08-17. "
        "The grant is narrower than it sounds, because what a conformant record attests here is "
        "unchanged: a human pinned this repository, these criteria and this remedy. It says "
        "nothing about the change, and it could not -- this service has no GitHub egress, so a "
        "human approving a factory record could not be shown what changed, and the acceptance "
        "criteria and rollback plan such a form would display are byte-identical across every "
        "record this policy has ever approved. The judgment that reads a machine-authored diff "
        "is the human-judgment acceptance criterion on the intent package, which disqualifies "
        "its unit from landing unattended and puts a person at the moment the diff exists. "
        "Nothing else moves. Both repositories, both criteria pairs, both remedies, both rollout "
        "pins and every landing condition are the objects version 3 declared. This admits a "
        "CLASS and not a REPOSITORY: a factory record for a repository this policy does not name "
        "is refused exactly as it was. And approval here remains the weakest thing this estate "
        "grants -- it means no objection, never go ahead, and every condition on the act is "
        "still evaluated by the party that can read GitHub at the moment it acts. "
        "One ceiling is inherited rather than chosen and is recorded above the landing "
        "conditions: criteria are keyed by repository and change classes are a flat set, so "
        "factory work is held to the same two criteria a lockfile bump is. Both are statements "
        "about the deployment mechanism, so both are true; requiring more of factory work would "
        "mean keying criteria on repository and class together, which is a separate decision."
    ),
    repositories=frozenset({"alobarquest/change-manager", "alobarquest/brain"}),
    change_classes=frozenset({"dependency-update", "factory-delivery"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA,
        "alobarquest/brain": _V3_BRAIN_CRITERIA,
    },
    rollback_plans={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK,
        "alobarquest/brain": _V3_BRAIN_ROLLBACK,
    },
    landing=_V4_LANDING,
)

# ---------------------------------------------------------------------------
# Version 5 -- Devon, 2026-08-30. Versions 1 to 4 above are retained verbatim.
# ---------------------------------------------------------------------------
#
# CHANGES WHAT DECIDES, AND NOTHING ELSE. Both repositories, both criteria pairs, both remedies,
# both rollout pins, both change classes and the freshness condition are the objects version 4
# declared. What moves is the one condition that asked about the version NUMBER: a bump whose
# required checks pass may now land whatever delta it states or fails to state.
#
# ADR-0036, and it is ADR-0034's rule applied to the deploying half of the estate. The reasoning is
# there in full; the two facts that decide it are that both lanes ALREADY gate on the required
# checks passing, so the update-type condition sat on top of that gate and said nothing about
# whether the bump works -- and that the condition could never reach the population it was holding.
# A requirement RANGE states no single delta, so no rule about deltas applies to it: five green
# pull requests across these two repositories sat unlandable for want of a parseable version
# number, while a `semver-patch` that broke at runtime would have passed.
#
# THE EXCLUSION IS THE SAME PRINCIPLE ADR-0034 KEPT: exclude where the required checks do not
# exercise what changed. On these repositories the rollout job is gated on a push to the default
# branch and runs on no pull request at all -- visible on every subject as a skipped job beside the
# passing ones -- so a change reaching it would be exercised for the first time by the very rollout
# it is supposed to gate. That is the workflow-automation ecosystem, which is what version 1 named
# and what this version keeps, now stated as the thing it is rather than inferred from a delta.
#
# IT IS NOT THE WHOLE OF THE PROTECTION AND IS NOT MEANT TO BE. The rollout pin below compares the
# pinned workflow's bytes at the pull request's own head, so a change to that FILE is refused
# whatever ecosystem it came from and whoever wrote it. The exclusion reaches what the pin cannot:
# a workflow this estate runs that no required check executes and no record pins.
#
# WHAT IS GIVEN UP, STATED PLAINLY. A major version bump whose tests pass but which breaks at
# runtime in a way those tests do not cover would reach production. It is bounded by one landing
# per repository per occurrence of the change window, by the pinned rollback plan above, and by
# the rollout watcher that observes the result hourly -- and it is the same exposure already
# accepted for patch and minor, at a larger blast radius.
#
# THIS REMOVES ONE OF TWO GUARDS KEEPING FACTORY-AUTHORED PULL REQUESTS OUT OF THE UNATTENDED
# LANE, which version 4 named as the condition of its own grant: `update_types` is what kept them
# out, and version 4 called that "a lane separation that depends on how somebody happened to word
# a title is not a separation". The other guard is the landing party's own selection on change
# class, which is unaffected -- so the door stays shut, on one belt rather than two, and on the
# belt that was chosen as a control rather than the one that worked by accident.
#
# WHY `update_types` IS SERVED AS EMPTY RATHER THAN DROPPED. The two sides of this contract are
# different processes that ship separately, so a landing party running the previous build will read
# this version's conditions. Dropping the key makes that reader unable to parse them at all, which
# refuses every record in both repositories rather than the ones this version is about; keeping it
# well-typed and EMPTY keeps the shape readable and permits nothing under it -- which is the right
# answer for a reader that cannot see this version's rule. It is a floor for a reader that has not
# learned the outcome rule, and deliberately not a statement that version 5 permits no delta.
_V5_LANDING: Final = LandingConditions(
    update_types=frozenset(),
    require_head_current_with_base=True,
    excluded_ecosystems=frozenset({GITHUB_ACTIONS}),
    rationale=(
        "WHAT DECIDES IS THE OUTCOME. A pull request the update bot opened may be landed "
        "unattended when its required checks pass, whatever version delta it states or fails to "
        "state. Versions 1 to 4 permitted patch and minor only, which asked about the version "
        "NUMBER and said nothing about whether the bump works -- both this lane and the cascade "
        "governing the repositories where landing changes nothing already serving ALREADY gate on "
        "the required checks passing, so the update-type condition sat on top of that gate. And it "
        "could not reach the population it was holding: a requirement RANGE states no single "
        "delta, so no rule about deltas applies to it, and five green pull requests across these "
        "two repositories were unlandable for want of a parseable version number while a patch "
        "that broke at runtime would have passed. ADR-0036, and ADR-0034's rule applied to the "
        "deploying half of the estate. "
        "THE EXCLUSION IS THE SAME PRINCIPLE ADR-0034 KEPT: exclude where the required checks do "
        "not exercise what changed. The rollout job on both these repositories is gated on a push "
        "to the default branch and runs on no pull request, which is visible on every subject as "
        "a skipped job beside the passing ones -- so a change reaching it would be exercised for "
        "the first time by the very rollout it is supposed to gate. That is the "
        "workflow-automation ecosystem, named here as the thing it is rather than inferred from a "
        "delta, and read by the landing party from the second segment of the branch the update "
        "bot opened. It is not the whole of the protection: the rollout pin below compares the "
        "pinned workflow's bytes at the pull request's own head, so a change to that FILE is "
        "refused whatever ecosystem it came from. The exclusion reaches what the pin cannot -- a "
        "workflow this estate runs that no required check executes and no record pins. "
        "WHAT IS GIVEN UP: a major bump whose tests pass but which breaks at runtime in a way "
        "those tests do not cover would reach production. It is bounded by one landing per "
        "repository per occurrence of the change window, by the rollback plan pinned above, and "
        "by the watcher that observes the rollout -- and it is the exposure already accepted for "
        "patch and minor at a larger blast radius. "
        "`update_types` is served EMPTY and that is a floor for a landing party running the "
        "previous build, not a statement that this version permits no delta: such a reader cannot "
        "see the rule above, and must permit nothing under a version it does not understand. "
        "Freshness is unchanged and is a policy condition rather than a strict branch, because a "
        "strict branch serialises human merges too and applies estate-wide behaviour nobody "
        "versions."
    ),
    rollout_workflows={
        "alobarquest/change-manager": WorkflowPin(
            path=".github/workflows/deploy.yml",
            # `191ec5a`, 2026-08-07 -- unchanged from versions 2, 3 and 4.
            blob_sha="a47d4b187c93971a5b5915ce87a963bd4ef35e30",
        ),
        "alobarquest/brain": WorkflowPin(
            path=".github/workflows/ci.yml",
            # `1d9e7d38`, 2026-08-14 -- unchanged from versions 3 and 4.
            blob_sha="c5c088719cd340f0071b875c6a82439292ed8756",
        ),
    },
)

V5: Final = DeployPolicy(
    version=5,
    decided="2026-08-30",
    rationale=(
        "Two repositories and two change classes, both unchanged from version 4. What version 5 "
        "changes is the one condition on the ACT that asked about a version number: a pull request "
        "the update bot opened may be landed unattended when its required checks pass, whatever "
        "delta it states or fails to state, except in the ecosystems those checks do not exercise. "
        "ADR-0036, decided 2026-08-30. "
        "The grant is narrower than it sounds. Everything a conformant record attests here is "
        "unchanged: a human pinned these repositories, these criteria and these remedies, and "
        "every condition on the act is still evaluated at the moment of the act by the party that "
        "can read GitHub. What moves is that the version delta stops being one of them, because "
        "it never said whether the bump works and it could not classify the population it was "
        "holding -- five green pull requests, every other condition met, refused for want of a "
        "parseable version number. "
        "Nothing else moves. Both repositories, both criteria pairs, both remedies, both rollout "
        "pins, both change classes and the freshness condition are the objects version 4 declared."
    ),
    repositories=frozenset({"alobarquest/change-manager", "alobarquest/brain"}),
    change_classes=frozenset({"dependency-update", "factory-delivery"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA,
        "alobarquest/brain": _V3_BRAIN_CRITERIA,
    },
    rollback_plans={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK,
        "alobarquest/brain": _V3_BRAIN_ROLLBACK,
    },
    landing=_V5_LANDING,
)

# Every version ever, retained. A record stores the number that approved it, so an approval stays
# re-evaluable after the policy has moved on.
REGISTRY: Final[dict[int, DeployPolicy]] = {
    policy.version: policy for policy in (V1, V2, V3, V4, V5)
}

CURRENT_VERSION: Final = 5


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
    """The conditions on the act, in the shape the landing party reads them.

    `rollout_workflows` is served keyed by repository. A repository absent from it has no pin
    under this version, and the landing party must read that as a refusal rather than as a waiver
    -- the reason is on `LandingConditions`, and the two readings differ for exactly the version
    that predates the field.
    """
    served = {
        "update_types": sorted(policy.landing.update_types),
        "require_head_current_with_base": policy.landing.require_head_current_with_base,
        "rationale": policy.landing.rationale,
        "rollout_workflows": {
            repository: {"path": pin.path, "blob_sha": pin.blob_sha}
            for repository, pin in sorted(policy.landing.rollout_workflows.items())
        },
    }
    # ADR-0036. THE KEY IS OMITTED BY A VERSION THAT DOES NOT DECIDE ON THE OUTCOME, and its
    # presence is what tells the landing party which rule to apply. Serving it as an empty list for
    # versions 1 to 4 would tell a reader that those versions exclude nothing -- true of the words
    # and false of the rule, since those versions decide by update type and exclude by omission.
    if policy.landing.excluded_ecosystems is not None:
        served["excluded_ecosystems"] = sorted(policy.landing.excluded_ecosystems)
    return served
