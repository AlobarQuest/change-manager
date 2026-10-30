"""Every SUPERSEDED deploy-policy version, retained verbatim.

`app.deploy_policy` holds the version in force and everything it still carries; this module holds
every superseded version, which no live path reads. They are kept because a record stores the number
of the version that approved it, and re-evaluating that approval later means looking the old version
up and finding what it actually said -- the editing contract in `app.deploy_policy`'s header. A
superseded version is never edited, here or anywhere.

WHICH WAY THE IMPORT RUNS, AND WHY. This module imports from `app.deploy_policy` and never the
reverse. Terms a superseded version shares with the current one -- change-manager's criteria and
remedy, brain's remedy and criteria, version 5's and version 9's conditions on the act -- are
defined once, beside the current version, and imported here, so every "the same object, not a
copy" note below stays literally true. What lives only here is what no version in force still
says.

`REGISTRY` and `policy_for` are here because they must see every version. Nothing in `app/` calls
them today: `deploy_changes._apply_policy` approves and re-approves against `current()` alone, and
the served routes project `current()`. They are the lookup a re-evaluation of an old approval
would use, and the tests pin every retained version through them.
"""

from typing import Final

from app.deploy_policy import (
    _V1_CHANGE_MANAGER_CRITERIA,
    _V1_CHANGE_MANAGER_ROLLBACK,
    _V3_BRAIN_ROLLBACK,
    _V5_LANDING,
    _V8_BRAIN_CRITERIA,
    _V9_LANDING,
    DEPENDABOT,
    DOCKER,
    FORK_SECURE_UPSTREAM_SYNC,
    SEMVER_MINOR,
    SEMVER_PATCH,
    V13,
    DeployPolicy,
    InertLanding,
    LandingConditions,
    WorkflowPin,
)

# ---------------------------------------------------------------------------
# Version 1 -- Devon, 2026-08-11.
# ---------------------------------------------------------------------------

# `_V1_CHANGE_MANAGER_CRITERIA` and `_V1_CHANGE_MANAGER_ROLLBACK` are still in force under the
# current version, so they live in `app.deploy_policy` and are imported here -- the same
# objects, not copies.

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

# `_V3_BRAIN_ROLLBACK` is still in force under the current version, so it lives in
# `app.deploy_policy`, with the reasoning for its wording, and is imported here -- the same
# object, not a copy.

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
# CHANGES WHAT DECIDES, AND NOTHING ELSE ABOUT THE TERMS. Both repositories, both criteria pairs,
# both remedies, both rollout pins, both change classes and the freshness condition are the objects
# version 4 declared. What moves is the one condition that asked about the version NUMBER: a bump
# whose required checks pass may now land whatever delta it states or fails to state.
#
# It is not free, and the cost is the one every version bump carries: raising CURRENT_VERSION
# supersedes every currently-approved record until it is re-approved, because the landing binds an
# approval to the version in force. This is a widening, so every held record still conforms and the
# producer re-stamps it on its next pass -- but between those two moments nothing lands.
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
#
# `_V5_LANDING` is still in force under the current version -- version 8 carries its terms and
# extends its rationale -- so it lives in `app.deploy_policy`, with the reasoning for serving
# `update_types` empty, and is imported here: the same object, not a copy.

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

# ---------------------------------------------------------------------------
# Version 6 -- Devon, 2026-08-31. Versions 1 to 5 above are retained verbatim.
# ---------------------------------------------------------------------------
#
# DECLARES A SECOND POPULATION AND CHANGES NOTHING ABOUT THE FIRST. Both repositories, both
# criteria pairs, both remedies, both rollout pins, both change classes and every landing
# condition are the objects version 5 declared -- `landing=_V5_LANDING` is that same object rather
# than a sixth transcription of one judgment, because version 6 makes no new statement about the
# deploying lane and a re-transcription would be a second copy of it.
#
# ADR-0038, and what it moves is WHERE the rule lives rather than what the rule is. Until now the
# repositories where landing on the default branch is inert were governed by a GitHub Actions
# workflow -- one blob, six repositories, arming GitHub's own auto-merge -- and the estate's
# producer learned what that workflow refuses by importing a hand transcription of it, keyed by
# blob sha. The workflow is being removed and the orchestrator becomes the merger, which leaves
# that rule with three readers and no holder: the party that lands, the producer that decides
# which bumps become factory work, and a person. It is declared here for the reason this module's
# header gives for everything else in it -- one holder, and the readers ask.
#
# WHY THE EXCLUSION IS `docker` HERE AND `github_actions` THERE, WHICH IS ONE PRINCIPLE AND NOT
# TWO RULES. Version 5 states the principle: exclude where the required checks do not exercise
# what changed. It reaches a different ecosystem in each population because the two populations
# fail to exercise different things, and both were measured rather than assumed.
#
#   In the DEPLOYING population the rollout job is gated on a push to the default branch and runs
#   on no pull request at all, visible on every subject as a skipped job beside the passing ones.
#   So a change to a workflow would be exercised for the first time by the very rollout it is
#   supposed to gate -- and that is the workflow-automation ecosystem.
#
#   In the INERT population there is no rollout job to skip; that is what makes it inert. What
#   goes unexercised instead is the base IMAGE. Two independent grounds, both from ADR-0023.
#   DOCKER TAGS ARE NOT SEMVER, so the compatibility promise a version number carries elsewhere is
#   absent: `python:3.14` is a language version occupying the minor digit, and 3.12 to 3.14
#   removes standard-library modules. And nothing RUNS the image -- the orchestrator's own gate
#   does build the real Dockerfile on every pull request, so a dependency with no wheel for the
#   new interpreter fails there, but no container is started and the suite executes on a
#   separately pinned interpreter. A package that installs cleanly and fails at import on a
#   removed module passes every check this estate has. Running the image is what would earn the
#   permission back.
#
#   Neither exclusion is a superset of the other, and neither is a mistake for the other. A
#   reader arriving at one having read the other should read the principle, not the literal.
#
# THE POPULATION IS ALL SIX REPOSITORIES THAT CARRIED THE WORKFLOW, `factory-runner` INCLUDED.
# Devon ruled it 2026-08-31, and it is the one member that needed ruling: ADR-0015 excluded that
# repository from the factory on a trust loop -- the runner verifying changes to itself. The
# reason that does not reach here is that ADR-0015 excluded DISPATCHING work into it, where a
# coding agent authors the change. This lane lands a change the update bot authored, whose diff is
# a version number, behind a required check that genuinely gates: of the six repositories declared
# below, `factory-runner` is the ONLY one carrying `enforce_admins: true`, chosen precisely
# because a bad merge there stops every dispatch. Different acts, different risks.
#
#   BE PRECISE ABOUT THAT CLAIM, because a first draft of this block said `factory-runner` is the
#   one repository in the ESTATE with `enforce_admins: true`, and that is false: measured
#   2026-08-31 against the protection API, it is true of `factory-runner`, `change-manager` and
#   `brain` and false of the other five here. The two extras are the DEPLOYING population this
#   same document declares, so the wider claim was false about its own other half. The narrower
#   one is what the argument needs and is what was measured.
#
# ADR-0038 records the blast radius as 8 of the 52 landings across the six over the preceding
# thirty days -- cited from that decision rather than re-measured here. Because the population is
# a declared list, removing a member later is a one-line version bump.
#
# EVERY MEMBER WAS CONFIRMED `inert` BY THE ESTATE'S OWN REGISTRY on 2026-08-31, and the
# declaration below is not the authority for it. The registry answers a repository-level
# determination read across all three trigger mechanisms -- every workflow, the repository's
# webhooks, and the hosting platform's own git integration -- because checking any one surface
# fails closed in one direction and fail-OPEN in the other. The landing party asks it again at the
# act and refuses on disagreement, so a repository that quietly starts redeploying stops being
# landable by this lane rather than being landed wrongly. A human admitting a repository here and
# the estate observing it are two statements, and both must hold.
#
# THE COST OF THE BUMP IS THE ONE EVERY VERSION CARRIES: raising CURRENT_VERSION supersedes every
# currently-approved record until it is re-approved, because the landing binds an approval to the
# version in force. This version is purely additive for the deploying lane -- nothing about the
# shape a proposal must have moved -- so every held record still conforms and the producer
# re-stamps it on its next hourly pass. Between those two moments nothing lands.
#
# WHAT IS GIVEN UP, STATED PLAINLY. The workflow this replaces was GitHub-native and landed even
# when this estate's own services were down; routine dependency hygiene now depends on them.
# Devon accepted that explicitly when ruling the direction. What is gained is that default-branch
# CI switches back on for all six: ADR-0038 records 38 landings by the workflow's arming identity
# firing ZERO `on: push` runs against 18 by the orchestrator's own merger firing 18. Cited from
# that decision rather than re-measured here.
_V6_INERT: Final = InertLanding(
    repositories=frozenset(
        {
            "alobarquest/orchestrator",
            "alobarquest/intent-packages",
            "alobarquest/security-standards",
            "alobarquest/infraops-mcp-server",
            "alobarquest/project-standards",
            "alobarquest/factory-runner",
        }
    ),
    permitted_authors=frozenset({DEPENDABOT}),
    excluded_ecosystems=frozenset({DOCKER}),
    require_head_current_with_base=True,
    rationale=(
        "WHERE LANDING ON THE DEFAULT BRANCH CHANGES NOTHING ALREADY SERVING. A pull request the "
        "update bot opened against one of these six repositories may be landed unattended when "
        "its required checks pass, whatever version delta it states or fails to state, except in "
        "the ecosystems those checks do not exercise. ADR-0038, decided 2026-08-31. This is not a "
        "new rule: it is the rule a GitHub Actions workflow enforced across these same six "
        "repositories, moved to the one place its three readers can ask rather than transcribe. "
        "THE AUTHOR IS A DECLARED CONDITION AND NOT AN ASSUMPTION. The workflow gated on it "
        "first, and it is the only thing bounding which pull requests this lane sees at all -- "
        "there is no change record here, so there is no upstream filter of the kind the "
        "deploying lane gets for free from a producer that refuses a non-bot pull request. Four "
        "of these six repositories carry a factory caller workflow, so a machine-authored pull "
        "request with green checks is a real subject rather than a hypothetical one, and this "
        "lane asks none of the questions the factory's own landing lane asks of one. "
        "THE EXCLUSION IS `docker`, AND IT IS THE SAME PRINCIPLE THE DEPLOYING LANE APPLIES TO A "
        "DIFFERENT ECOSYSTEM: exclude where the required checks do not exercise what changed. "
        "There the rollout job runs on no pull request, so a workflow-automation bump would be "
        "exercised for the first time by the rollout it is meant to gate. Here there is no "
        "rollout at all -- that is what makes these repositories inert -- and what goes "
        "unexercised is the base image. Docker tags are not semver, so a version number promises "
        "no compatibility, and nothing runs the image: a build of the real Dockerfile is part of "
        "the checks, but no container is started, so a package that installs cleanly and fails at "
        "import on a removed standard-library module passes everything. Running the image is what "
        "would earn the permission back. A reader who has read one exclusion should carry the "
        "principle across and not the literal; neither is a superset of the other. "
        "FRESHNESS IS REQUIRED, WHICH IS A TIGHTENING OVER THE WORKFLOW THIS REPLACES, and the "
        "reason is about the default branch rather than about production: a squash of a behind "
        "head produces a tree nothing executed, and that branch is what every build session "
        "branches from and what default-branch CI now runs on. "
        "NO PACE CONDITION ACCOMPANIES IT, AND THE ABSENCE IS DECIDED RATHER THAN OMITTED. Given "
        "freshness, a landing stales every sibling, so at most one pull request per repository is "
        "landable per pass and the rest are freshened for the next one -- freshness serialises "
        "this lane by itself, and a pace rule would be a second mechanism producing an effect the "
        "first already produces. The deploying lane does carry one, and the difference is not an "
        "oversight: there, pace bounds how often something already serving may change, which is a "
        "fact about production rather than about staleness. There is no change window here for the "
        "same reason, and no change record: a record exists to carry acceptance criteria and a "
        "rollback plan for a deploy, and none of the three has a subject in a repository where "
        "landing deploys nothing. "
        "WHAT IS GIVEN UP: the workflow this replaces was GitHub-native and landed even when this "
        "estate's own services were down, and routine dependency hygiene now depends on them. "
        "What is gained is that default-branch CI runs on these landings again, which it did not "
        "under the workflow."
    ),
)

V6: Final = DeployPolicy(
    version=6,
    decided="2026-08-31",
    rationale=(
        "Two populations. The first is unchanged in every term from version 5 -- two "
        "repositories, two change classes, both criteria pairs, both remedies, both rollout pins "
        "and every condition on the act, which are the objects version 5 declared. What version 6 "
        "adds is a declaration of the SECOND population: the six repositories where landing on the "
        "default branch changes nothing already serving, and the conditions on landing there. "
        "ADR-0038, decided 2026-08-31. "
        "It moves where a rule lives rather than what the rule is. Those six were governed by a "
        "GitHub Actions workflow that armed GitHub's own auto-merge, byte-identical across all "
        "six, and the estate's producer learned what it refuses by importing a hand transcription "
        "of it. Removing the workflow and making the orchestrator the merger would leave that rule "
        "with three readers and no holder, so it is declared here, where a human edits it and "
        "where it is versioned -- and every condition on the act is still evaluated at the moment "
        "of the act by the party that can read GitHub, exactly as the deploying lane's are. "
        "The two populations are disjoint and must stay so: a repository named by both would be "
        "claimed by two lanes on different terms. Nothing keyed on the deploying population "
        "changes, and a version that quietly widened it while wearing this rationale would fail "
        "the test that says so."
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
    # The SAME OBJECT version 5 declared, not a copy of it. Version 6 makes no new statement about
    # the deploying lane, and a re-transcription would be a second copy of one judgment -- the
    # thing the criteria and remedy constants above are shared to avoid.
    landing=_V5_LANDING,
    inert_landing=_V6_INERT,
)

# ---------------------------------------------------------------------------
# Version 7 -- Devon, 2026-09-05.
# ---------------------------------------------------------------------------

# `OCTO_UPSTREAM_SYNC` and `_V7_INERT` were in force from version 7 to version 9, and lived in
# `app.deploy_policy` until version 10 renamed the sync author. Moved here unedited.

# The App that authors both forks' upstream-sync pull requests, in the REST spelling -- which is
# what the landing party compares against. `gh` answers `app/octo-upstream-sync` for the same
# account, and that is NOT this string. App id 4094707, installed on the two forks and nowhere
# else. Chosen over `github-actions[bot]` on 2026-09-05 precisely because this list permits by
# NAME: `github-actions[bot]` is the identity of ANY workflow in a repository, so declaring it
# would grant this lane to every workflow-authored pull request there rather than to the sync.
OCTO_UPSTREAM_SYNC: Final = "octo-upstream-sync[bot]"


_V7_INERT: Final = InertLanding(
    repositories=frozenset(
        {
            "alobarquest/orchestrator",
            "alobarquest/intent-packages",
            "alobarquest/security-standards",
            "alobarquest/infraops-mcp-server",
            "alobarquest/project-standards",
            "alobarquest/factory-runner",
            # The two forks, added 2026-09-05. Both answer `landing: "inert"` in App Brain --
            # rtk determined 2026-09-02, claude-octopus 2026-08-02 -- so landing on their default
            # branches changes nothing already serving, which is this population's whole criterion.
            "alobarquest/rtk",
            "alobarquest/claude-octopus",
        }
    ),
    permitted_authors=frozenset({DEPENDABOT, OCTO_UPSTREAM_SYNC}),
    excluded_ecosystems=frozenset({DOCKER}),
    require_head_current_with_base=True,
    non_ecosystem_authors=frozenset({OCTO_UPSTREAM_SYNC}),
    rationale=(
        "The same rule ADR-0038 declared, over two more repositories and one more author. "
        "Both forks carry a daily "
        "workflow that syncs an upstream release, reviews it, hardens it and opens ONE rolling "
        "pull request -- and until 2026-09-05 nothing landed it. rtk's sat open from 2026-06-29 "
        "while its contents were refreshed daily; the operator was six minor versions behind the "
        "release his own lane had already reviewed. "
        "WHAT MADE THEM ADMISSIBLE IS NOT THIS VERSION. Both were repositories where a pull "
        "request read `mergeable_state: CLEAN` only because NOTHING COULD FAIL -- rtk had one "
        "workflow, the sync itself, and neither fork had a required status check. Each now has a "
        "gate that reports on every pull request and is required on `main`: rtk's `build and "
        "test` builds and tests the merged tree, claude-octopus's `hardening and syntax` runs the "
        "hardener's own self-test and parses every file that becomes a hook on the operator's "
        "machine. Those are what `CLEAN` now means there, and this version rests on them. "
        "THE AUTHOR IS `octo-upstream-sync[bot]` AND NOT `github-actions[bot]`, which is a choice "
        "and not a detail. rtk's sync authenticated as `GITHUB_TOKEN` until 2026-09-05, so its "
        "author was the identity of ANY workflow in that repository; permitting it would have "
        "granted this lane to every workflow-authored pull request there. The sync now mints a "
        "token from an App installed on the two forks and nowhere else. "
        "AN UPSTREAM SYNC IS NOT A BUMP, which is why it is named in `non_ecosystem_authors`. It "
        "states no version delta and belongs to no package ecosystem, so the ecosystem exclusion "
        "has no purchase on it -- asking is the wrong question rather than one it failed to "
        "answer. ADR-0041 (orchestrator) decided that the exemption is DECLARED here rather than "
        "inferred from a branch name, because inferring it would let any branch name switch the "
        "ecosystem bound off. Dependabot keeps that bound in every term. "
        "The deploying population and every term keyed off it are the objects version 5 declared "
        "and version 6 carried, unchanged. The two populations remain disjoint."
    ),
)

V7: Final = DeployPolicy(
    version=7,
    decided="2026-09-05",
    rationale=(
        "Version 6's two populations, with the inert one widened by two repositories and one "
        "author, and one new term on the act. Nothing about the deploying lane changes: it is the "
        "same objects, and the test that says the populations stay disjoint still says so. "
        "The widening is the end of a lane that produced reviewed, hardened pull requests for "
        "months and landed none of them."
    ),
    repositories=V6.repositories,
    change_classes=V6.change_classes,
    risks=V6.risks,
    acceptance_criteria=V6.acceptance_criteria,
    rollback_plans=V6.rollback_plans,
    # The SAME OBJECT versions 5 and 6 declared, not a copy: version 7 makes no new statement
    # about the deploying lane.
    landing=_V5_LANDING,
    inert_landing=_V7_INERT,
)


# THE SAME TERMS ON THE ACT VERSION 5 DECIDED, with one repository's rollout re-pinned. The two
# halves move together or not at all: the criteria above describe the bytes at `7cf6ca2d`, and a
# pin left on `c5c08871` would refuse at the act every record those criteria approve -- which is
# the state this version exists to end, and which held brain's queue from 2026-09-07.
#
# change-manager's pin is the SAME OBJECT version 5 declared rather than a copy: nothing about
# that repository's rollout has moved, and re-transcribing it would be a second copy of one
# judgment.
_V8_LANDING: Final = LandingConditions(
    update_types=_V5_LANDING.update_types,
    require_head_current_with_base=_V5_LANDING.require_head_current_with_base,
    excluded_ecosystems=_V5_LANDING.excluded_ecosystems,
    rationale=(
        _V5_LANDING.rationale + " VERSION 8 RE-PINS BRAIN'S ROLLOUT at `7cf6ca2d`, the "
        "revision that fails a trigger naming no deployment and fails at once on a deployment "
        "Coolify reports as failed. Nothing else about the act changes."
    ),
    rollout_workflows={
        "alobarquest/change-manager": _V5_LANDING.rollout_workflows["alobarquest/change-manager"],
        "alobarquest/brain": WorkflowPin(
            path=".github/workflows/ci.yml",
            # `brain#62`, 2026-09-07 -- supersedes `c5c088719`, which versions 3 to 7 pinned.
            blob_sha="7cf6ca2d2a508b1643cdb5ac0d5390357f397d54",
        ),
    },
)


V8: Final = DeployPolicy(
    version=8,
    decided="2026-09-16",
    rationale=(
        "Version 7's populations and terms, with brain's rollout workflow re-pinned and the "
        "criteria it attests re-ratified. Nothing is widened: the same two repositories, the "
        "same two change classes, the same risk, the same remedies, the same conditions on the "
        "act. "
        "WHY IT EXISTS. brain#62 changed what a green rollout of that repository proves, so the "
        "producer began deriving criteria that no version had ratified and every brain record "
        "stopped being approved -- three green pull requests waited from 2026-09-10 for a human "
        "to read the diff. That is the mechanism working: a rollout workflow changing under a "
        "standing approval is the one thing this policy notices, and the remedy it asks for is "
        "exactly this bump. "
        "WHAT WAS READ BEFORE RATIFYING. The new bytes attest strictly more than the old: a "
        "trigger whose 2xx names no deployment now fails, and a deployment Coolify reports as "
        "failed now fails the run at once instead of at the deadline. The revision poll that "
        "version 3 admitted brain for is unchanged and remains the authority on success, so the "
        "guarantee the rollback plan attaches to has not moved -- which is why the remedy is "
        "version 3's, unedited."
    ),
    # The repositories versions 3 to 7 declared, and the change classes and risk of versions 4
    # to 7, unchanged.
    repositories=frozenset({"alobarquest/change-manager", "alobarquest/brain"}),
    change_classes=frozenset({"dependency-update", "factory-delivery"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA,
        "alobarquest/brain": _V8_BRAIN_CRITERIA,
    },
    rollback_plans={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK,
        "alobarquest/brain": _V3_BRAIN_ROLLBACK,
    },
    landing=_V8_LANDING,
    # The SAME OBJECT version 7 declared: this version makes no statement about the inert lane.
    inert_landing=_V7_INERT,
)


# ---------------------------------------------------------------------------
# Version 9 -- Devon, 2026-09-28.
# ---------------------------------------------------------------------------

V9: Final = DeployPolicy(
    version=9,
    decided="2026-09-28",
    rationale=(
        "Version 8's populations and terms, with both rollout workflows re-pinned. Nothing is "
        "widened: the same two repositories, the same two change classes, the same risk, the "
        "same criteria, the same remedies, the same conditions on the act. "
        "WHY IT EXISTS. Both repositories moved to Python 3.14, which edited the setup steps of "
        "each rollout workflow and so moved both blobs. A pin left on the old bytes would refuse "
        "every landing at the act. "
        "WHAT WAS READ BEFORE RATIFYING. In both workflows the production job's trigger step and "
        "verify step are byte-identical to the revisions version 8 pinned, and the producer "
        "derives the same criteria text from the new bytes as from the old. So what a green "
        "rollout proves is unchanged, and so are the criteria and the remedy attached to them."
    ),
    repositories=frozenset({"alobarquest/change-manager", "alobarquest/brain"}),
    change_classes=frozenset({"dependency-update", "factory-delivery"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA,
        "alobarquest/brain": _V8_BRAIN_CRITERIA,
    },
    rollback_plans={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK,
        "alobarquest/brain": _V3_BRAIN_ROLLBACK,
    },
    landing=_V9_LANDING,
    # The SAME OBJECT versions 7 and 8 declared: this version makes no statement about the inert
    # lane.
    inert_landing=_V7_INERT,
)


# ---------------------------------------------------------------------------
# Version 10 -- Devon, 2026-10-19.
# ---------------------------------------------------------------------------

# VERSION 7'S INERT POPULATION AND TERMS, with the sync author's login renamed and nothing else
# moved. The same eight repositories, the same exclusion, the same freshness condition, and one
# exempted author, as before -- the same App, under the name GitHub now serves for it.
_V10_INERT: Final = InertLanding(
    repositories=frozenset(
        {
            "alobarquest/orchestrator",
            "alobarquest/intent-packages",
            "alobarquest/security-standards",
            "alobarquest/infraops-mcp-server",
            "alobarquest/project-standards",
            "alobarquest/factory-runner",
            # The two forks, added by version 7. Both answer `landing: "inert"` in App Brain. The
            # sync App's installation also reaches `alobarquest/rea` since 2026-10-19; it is NOT
            # declared here, so a pull request there is refused on its repository whoever wrote it.
            "alobarquest/rtk",
            "alobarquest/claude-octopus",
        }
    ),
    permitted_authors=frozenset({DEPENDABOT, FORK_SECURE_UPSTREAM_SYNC}),
    excluded_ecosystems=frozenset({DOCKER}),
    require_head_current_with_base=True,
    non_ecosystem_authors=frozenset({FORK_SECURE_UPSTREAM_SYNC}),
    rationale=(
        "The rule ADR-0038 declared, over the eight repositories and two authors version 7 "
        "admitted, with one author's login renamed. "
        "WHAT CHANGED. The App that opens both forks' upstream-sync pull requests -- App id "
        "4094707 -- was renamed on 2026-10-19 from `octo-upstream-sync` to "
        "`fork-secure-upstream-sync`. GitHub renamed its bot user with it: the user id is "
        "unchanged, `pull_request.user.login` now answers `fork-secure-upstream-sync[bot]`, and "
        "the old login answers 404. This block permits by NAME, so from the rename until this "
        "version every sync pull request was refused on its author. "
        "NOTHING IS WIDENED. It is the same App and the same installation, so the author this "
        "block names is the identity versions 7 to 9 decided to permit, under the name GitHub "
        "now serves. The repositories, the docker exclusion, the freshness condition and the "
        "ADR-0041 exemption are unchanged; the exemption names the same App by its new login, "
        "and Dependabot keeps the ecosystem bound in every term. "
        "WHY NOT `github-actions[bot]`, still: that is the identity of ANY workflow in a "
        "repository, so permitting it would grant this lane to every workflow-authored pull "
        "request there rather than to the sync. "
        "WHAT THIS VERSION DOES NOT ADMIT. The App's installation now also reaches "
        "`alobarquest/rea`. That repository is not in this population, so the author condition "
        "does not reach it: a pull request there is refused on its repository. Admitting it is a "
        "separate decision, for a later version, once it carries required checks. "
        "The deploying population and every term keyed off it are version 9's objects, "
        "unchanged. The two populations remain disjoint."
    ),
)


V10: Final = DeployPolicy(
    version=10,
    decided="2026-10-19",
    rationale=(
        "Version 9's populations and terms, with the inert lane's sync author renamed. Nothing "
        "is widened: the same two deploying repositories, the same two change classes, the same "
        "risk, the same criteria, the same remedies, the same rollout pins, the same conditions "
        "on the act, and the same eight inert repositories. "
        "WHY IT EXISTS. The GitHub App that opens the forks' upstream-sync pull requests, App id "
        "4094707, was renamed from `octo-upstream-sync` to `fork-secure-upstream-sync` on "
        "2026-10-19, and GitHub renamed its bot user with it. The inert lane permits authors by "
        "login, so it began refusing the sync pull requests on rtk and claude-octopus. The App "
        "and its installation are the same; only the name moved. "
        "The installation now also reaches alobarquest/rea, which this version does not admit."
    ),
    repositories=frozenset({"alobarquest/change-manager", "alobarquest/brain"}),
    change_classes=frozenset({"dependency-update", "factory-delivery"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA,
        "alobarquest/brain": _V8_BRAIN_CRITERIA,
    },
    rollback_plans={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK,
        "alobarquest/brain": _V3_BRAIN_ROLLBACK,
    },
    # The SAME OBJECT version 9 declared: this version makes no statement about the deploying lane.
    landing=_V9_LANDING,
    inert_landing=_V10_INERT,
)


# ---------------------------------------------------------------------------
# Version 11 -- Devon, 2026-10-19.
# ---------------------------------------------------------------------------

# VERSION 10'S INERT POPULATION AND TERMS, with one more fork. The same authors, the same
# exclusion, the same freshness condition and the same exempted author.
_V11_INERT: Final = InertLanding(
    repositories=frozenset(
        {
            "alobarquest/orchestrator",
            "alobarquest/intent-packages",
            "alobarquest/security-standards",
            "alobarquest/infraops-mcp-server",
            "alobarquest/project-standards",
            "alobarquest/factory-runner",
            # The two forks version 7 added. Both answer `landing: "inert"` in App Brain.
            "alobarquest/rtk",
            "alobarquest/claude-octopus",
            # Added by version 11, 2026-10-19. A fork of morluto/rea, a tool installed on the
            # operator's machine; it answers `landing: "inert"` in App Brain.
            "alobarquest/rea",
        }
    ),
    permitted_authors=frozenset({DEPENDABOT, FORK_SECURE_UPSTREAM_SYNC}),
    excluded_ecosystems=frozenset({DOCKER}),
    require_head_current_with_base=True,
    non_ecosystem_authors=frozenset({FORK_SECURE_UPSTREAM_SYNC}),
    rationale=(
        "The rule ADR-0038 declared, over the eight repositories version 10 named and one more "
        "fork, with the same two authors. "
        "WHAT IS ADDED. alobarquest/rea is the operator's fork of morluto/rea, a reverse-"
        "engineering command-line tool and MCP server that the orchestrator's tool-installer "
        "lane installs on the operator's machine. Nothing serves from it, so landing on its "
        "default branch changes nothing already serving, which is this population's whole "
        "criterion. Its default branch was rebuilt at upstream release `rea-agents-6.6.0` with "
        "upstream's whole `.github/` removed, then onboarded with the orchestrator's fork-sync "
        "tool, so its upstream-sync pull requests are opened by the same App, App id 4094707, "
        "under the login version 10 named. "
        "WHAT `CLEAN` MEANS THERE, which is what this version rests on, as version 7 rested on "
        "the forks' gates. Two checks are required on main, both pinned to GitHub Actions: "
        "`build and test` installs with `npm ci --ignore-scripts` and runs the configured build "
        "and tests; `security review` is a fail-closed review that reads its gate from the BASE "
        "branch. It reports deterministic findings for watched paths, binaries, submodule "
        "pointers, npm lifecycle scripts, `bin` entries, `.npmrc` and non-registry dependencies, "
        "lockfile sources, integrity and install scripts, and `npm audit --audit-level=high`, "
        "and adds a model review of the full diff. Any unacknowledged finding, or a review that "
        "could not run, fails the check. "
        "rtk now carries the same two required checks, which makes the gate version 7 relied on "
        "there stronger than the one it described. "
        "NOTHING ELSE IS WIDENED. The authors, the docker exclusion, the freshness condition and "
        "the ADR-0041 exemption are version 10's. Dependabot keeps the ecosystem bound in every "
        "term, and `github-actions[bot]` is still not an author, because it is the identity of "
        "ANY workflow in a repository. "
        "The deploying population and every term keyed off it are version 10's objects, "
        "unchanged. The two populations remain disjoint."
    ),
)


V11: Final = DeployPolicy(
    version=11,
    decided="2026-10-19",
    rationale=(
        "Version 10's populations and terms, with one repository added to the inert lane: "
        "alobarquest/rea. Nothing else is widened: the same two deploying repositories, the same "
        "two change classes, the same risk, the same criteria, the same remedies, the same "
        "rollout pins, the same conditions on the act, and the same inert authors and terms. "
        "WHY IT EXISTS. rea is the operator's fork of morluto/rea, onboarded with the "
        "orchestrator's fork-sync tool, and it now carries two required checks on main, "
        "`build and test` and `security review`. Those are what a clean pull request there "
        "means, and they are what version 10 said rea needed before it could be admitted."
    ),
    repositories=frozenset({"alobarquest/change-manager", "alobarquest/brain"}),
    change_classes=frozenset({"dependency-update", "factory-delivery"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA,
        "alobarquest/brain": _V8_BRAIN_CRITERIA,
    },
    rollback_plans={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK,
        "alobarquest/brain": _V3_BRAIN_ROLLBACK,
    },
    # The SAME OBJECT versions 9 and 10 declared: this version makes no statement about the
    # deploying lane.
    landing=_V9_LANDING,
    inert_landing=_V11_INERT,
)


# ---------------------------------------------------------------------------
# Version 12 -- Devon, 2026-10-21.
# ---------------------------------------------------------------------------

# VERSION 11'S INERT POPULATION AND TERMS, with two more forks. The same authors, the same
# exclusion, the same freshness condition and the same exempted author.
_V12_INERT: Final = InertLanding(
    repositories=frozenset(
        {
            "alobarquest/orchestrator",
            "alobarquest/intent-packages",
            "alobarquest/security-standards",
            "alobarquest/infraops-mcp-server",
            "alobarquest/project-standards",
            "alobarquest/factory-runner",
            # The two forks version 7 added. Both answer `landing: "inert"` in App Brain.
            "alobarquest/rtk",
            "alobarquest/claude-octopus",
            # Added by version 11, 2026-10-19. A fork of morluto/rea, a tool installed on the
            # operator's machine; it answers `landing: "inert"` in App Brain.
            "alobarquest/rea",
            # Added by version 12, 2026-10-21. Forks of EtienneLescot/n8n-as-code and
            # EtienneLescot/n8n-manager, tools installed on the operator's machine; both answer
            # `landing: "inert"` in App Brain.
            "alobarquest/n8n-as-code",
            "alobarquest/n8n-manager",
        }
    ),
    permitted_authors=frozenset({DEPENDABOT, FORK_SECURE_UPSTREAM_SYNC}),
    excluded_ecosystems=frozenset({DOCKER}),
    require_head_current_with_base=True,
    non_ecosystem_authors=frozenset({FORK_SECURE_UPSTREAM_SYNC}),
    rationale=(
        "The rule ADR-0038 declared, over the nine repositories version 11 named and two more "
        "forks, with the same two authors. "
        "WHAT IS ADDED. alobarquest/n8n-as-code is the operator's fork of "
        "EtienneLescot/n8n-as-code, an n8n command-line tool and the Claude Code plugin that "
        "drives it; alobarquest/n8n-manager is the operator's fork of EtienneLescot/n8n-manager, "
        "the runtime n8n-as-code depends on and its plugin runs. Both are tools for the "
        "operator's machine and nothing serves from either, so landing on their default "
        "branches changes nothing already serving, which is this population's whole criterion. "
        "Each default branch was rebuilt at an upstream release with upstream's whole `.github/` "
        "removed, then onboarded with the orchestrator's fork-sync tool, so their upstream-sync "
        "pull requests are opened by the same App, App id 4094707, under the login version 10 "
        "named. "
        "WHAT `CLEAN` MEANS THERE. Both carry the two required checks version 11 described for "
        "rea, pinned to GitHub Actions: `build and test` and the fail-closed `security review` "
        "read from the BASE branch. n8n-as-code's upstream commits no lockfile, so its sync "
        "resolves one as of each release's commit date, outside upstream's tree with no "
        "upstream configuration and no scripts or git fetches, and commits it to the sync pull "
        "request; the review then audits and reviews that lockfile like any other "
        "(orchestrator ADR-0056 amendment 2). "
        "NOTHING ELSE IS WIDENED. The authors, the docker exclusion, the freshness condition and "
        "the ADR-0041 exemption are version 11's. Dependabot keeps the ecosystem bound in every "
        "term, and `github-actions[bot]` is still not an author, because it is the identity of "
        "ANY workflow in a repository. "
        "The deploying population and every term keyed off it are version 11's objects, "
        "unchanged. The two populations remain disjoint."
    ),
)


V12: Final = DeployPolicy(
    version=12,
    decided="2026-10-21",
    rationale=(
        "Version 11's populations and terms, with two repositories added to the inert lane: "
        "alobarquest/n8n-as-code and alobarquest/n8n-manager. Nothing else is widened: the same "
        "two deploying repositories, the same two change classes, the same risk, the same "
        "criteria, the same remedies, the same rollout pins, the same conditions on the act, and "
        "the same inert authors and terms. "
        "WHY IT EXISTS. Both are the operator's forks, onboarded with the orchestrator's "
        "fork-sync tool on 2026-10-21, and each carries two required checks on main, "
        "`build and test` and `security review`, which are what a clean pull request there means."
    ),
    repositories=frozenset({"alobarquest/change-manager", "alobarquest/brain"}),
    change_classes=frozenset({"dependency-update", "factory-delivery"}),
    risks=frozenset({"caution"}),
    acceptance_criteria={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_CRITERIA,
        "alobarquest/brain": _V8_BRAIN_CRITERIA,
    },
    rollback_plans={
        "alobarquest/change-manager": _V1_CHANGE_MANAGER_ROLLBACK,
        "alobarquest/brain": _V3_BRAIN_ROLLBACK,
    },
    # The SAME OBJECT versions 9 to 11 declared: this version makes no statement about the
    # deploying lane.
    landing=_V9_LANDING,
    inert_landing=_V12_INERT,
)


# Every version ever, retained. A record stores the number that approved it, so an approval stays
# re-evaluable after the policy has moved on.
#
# ONE VERSION PER LINE, so `scripts/release_inert_repository.py` adds a version by adding a line.
REGISTRY: Final[dict[int, DeployPolicy]] = {
    policy.version: policy
    for policy in (
        V1,
        V2,
        V3,
        V4,
        V5,
        V6,
        V7,
        V8,
        V9,
        V10,
        V11,
        V12,
        V13,
    )
}


def policy_for(version: int) -> DeployPolicy | None:
    """The version a record was approved under, or None if this build does not know it.

    None is a finding for the caller, never a skip: a record naming a version this build cannot
    produce is a record whose approval cannot be re-derived.
    """
    return REGISTRY.get(version)
