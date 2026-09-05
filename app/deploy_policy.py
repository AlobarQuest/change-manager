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

# The workflow-automation ecosystem, spelled as the update bot spells it in a BRANCH NAME, which
# is where the landing party reads it. WITH AN UNDERSCORE, and that is not a detail.
#
# THE VOCABULARY IS THE BRANCH SEGMENT, NOT `package-ecosystem`, and the two disagree. A
# `dependabot.yml` says `github-actions`; the branch says `github_actions`, because the value the
# update bot normalises into `dependabot/<ecosystem>/<rest>` is the identifier rather than the
# configured spelling. `npm` configures as `npm` and appears as `npm_and_yarn`. An author adding a
# member here must read a real branch name, not a config file.
#
# AND A MISSPELLING HERE FAILS THE UNSAFE WAY, which is the opposite of the same mistake in the
# other lane. There the ecosystem sits on the PERMITTING side, so the estate's landing ledger
# records a gate revision that compared the hyphenated form, matched nothing, and permitted
# nothing -- it under-permitted, invisibly, which is why the ledger transcribes the literal rather
# than correcting it. Here the ecosystem sits on the EXCLUDING side: a member nothing matches
# excludes nothing, so the landing party ADMITS exactly the ecosystem this exclusion exists for.
# That is why the spelling is pinned by a test rather than trusted to review.
GITHUB_ACTIONS: Final = "github_actions"

# The container-image ecosystem, spelled the same way on both sides -- and checked rather than
# assumed, because the constant above exists precisely because that is not always true.
# `dependabot.yml` says `docker`, and the branch the update bot opens says `docker` too: read from
# `dependabot/docker/python-3.14-slim`, the estate's one open image bump, on 2026-08-31.
#
# IT SITS ON THE EXCLUDING SIDE, so the failure direction is the unsafe one described above: a
# member nothing matches excludes nothing, and the landing party then ADMITS exactly the ecosystem
# this exclusion exists for. Pinned by a test for that reason and not for tidiness.
DOCKER: Final = "docker"

# The update bot, spelled as `pull_request.user.login` spells it -- and THERE ARE TWO
# SPELLINGS OF ONE IDENTITY, which is the reason this is a constant rather than a literal.
# GitHub's REST `pulls/{n}` answers `dependabot[bot]` with `user.type == 'Bot'`; `gh pr view
# --json author` answers `app/dependabot` for the same pull request, measured on
# alobarquest/orchestrator#3 on 2026-08-31. The workflow this rule comes from keys on the
# first (`github.event.pull_request.user.login == 'dependabot[bot]'`), so that is the one
# declared here.
#
# IT SITS ON THE PERMITTING SIDE, so a wrong spelling here under-permits and the lane simply
# stops landing -- the safe direction, and therefore the one nobody notices. That is the
# opposite of the exclusions above and is why both are pinned by tests rather than one.
DEPENDABOT: Final = "dependabot[bot]"

# The App that authors both forks' upstream-sync pull requests, in the REST spelling -- which is
# what the landing party compares against. `gh` answers `app/octo-upstream-sync` for the same
# account, and that is NOT this string. App id 4094707, installed on the two forks and nowhere
# else. Chosen over `github-actions[bot]` on 2026-09-05 precisely because this list permits by
# NAME: `github-actions[bot]` is the identity of ANY workflow in a repository, so declaring it
# would grant this lane to every workflow-authored pull request there rather than to the sync.
OCTO_UPSTREAM_SYNC: Final = "octo-upstream-sync[bot]"


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
    # MEMBERS ARE SPELLED AS A BRANCH SPELLS THEM -- the second segment of
    # `dependabot/<ecosystem>/<rest>` -- and NOT as `dependabot.yml` spells them. See
    # `GITHUB_ACTIONS` above for why the two differ and why getting it wrong admits rather than
    # refuses.
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
class InertLanding:
    """Where landing on the default branch changes NOTHING already serving, and the terms there.

    ADR-0038. The second population this document governs, and the one it was not originally
    about. `DeployPolicy.repositories` and every term keyed off it belong to the DEPLOYING lane:
    landing there redeploys production, so a change record, acceptance criteria, a remedy and a
    rollout pin each have a subject. Here none of them does -- there is no rollout to attest and
    nothing serving to roll back -- so this block declares a POPULATION and the CONDITIONS ON THE
    ACT, and nothing else.

    WHY IT IS HERE RATHER THAN IN A SIBLING DOCUMENT. This rule had three readers and no holder:
    the party that lands, the producer that decides what will not land unattended, and a person.
    It lived as a GitHub workflow, byte-identical across six repositories, transcribed by hand
    into a fourth place keyed by blob sha. A sibling document would be the second holder this
    module's header exists to prevent; a sibling FIELD is one holder with two populations.

    THE TWO POPULATIONS MUST STAY DISJOINT, and a test says so rather than a comment. A repository
    named by both would be claimed by two landing lanes on different terms, and nothing downstream
    compares the answers.

    WHAT IS DELIBERATELY NOT A FIELD: no change window, no pace, no acceptance criteria, no
    rollback plan, no rollout pin. Every one of those is a statement about something already
    serving, and declaring them empty or false here would record a decision nobody made -- the
    failure `excluded_ecosystems` omits its key to avoid, one level up. **The fields below are
    therefore the WHOLE of what this document says about the act for this population**: a landing
    party may not add a condition this block does not state, and may not drop one it does.

    WHICH IS WHY `permitted_authors` IS A FIELD RATHER THAN A SENTENCE IN THE RATIONALE, and it
    was nearly the latter. The rule this block moves gated on the author first -- the workflow's
    own condition is `github.event.pull_request.user.login == 'dependabot[bot]'` -- and leaving
    that in prose would have left a landing party two readings, neither safe: apply a condition
    the document does not declare, or drop it. The second is a real fail-open and not a
    hypothetical one. Four of the six repositories declared below carry a factory caller
    workflow (measured 2026-08-31), so a FACTORY-opened pull request there with green checks
    would otherwise be landable by a lane that never asks whether the unit completed, whether the
    verifier decided its criteria from observed evidence, or whether an authority approval is
    bound to the envelope. The deploying lane needs no such field because its producer refuses a
    non-bot pull request upstream, so its subjects are bot-only by construction; this lane has no
    record and therefore no upstream filter, and the author condition is the only thing bounding
    which pull requests it ever sees. Version 4 reached the same conclusion about the deploying
    lane's own gap and put it exactly here: the refusal belongs on the party that reads GitHub,
    keyed on something this document NAMES.

    THE VERSION A LANDING PARTY ATTRIBUTES A LANDING TO IS THE DOCUMENT'S, NOT THIS BLOCK'S. One
    `version` covers both populations, so a later version that moves only a rollout pin in the
    deploying half also re-stamps what an inert landing is attributed to. That follows from one
    holder and is the right trade; it is recorded because a reader of those attributions will
    otherwise assume the number tracks the rule it names.

    THIS SERVICE STILL EVALUATES NOTHING, like every other term here. Whether a pull request was
    opened by the update bot, which ecosystem the second segment of its branch names, whether its
    required checks passed and whether its head is current with the base all live in GitHub, and
    the landing party is the one that can read them.
    """

    repositories: frozenset[str]
    # WHOSE pull requests. Spelled as `pull_request.user.login` spells it -- see `DEPENDABOT`
    # above, where two spellings of one identity are why this is a constant. It permits rather
    # than excludes, so a wrong value under-permits and the lane goes quiet.
    permitted_authors: frozenset[str]
    # Spelled as a BRANCH spells it, and read from a real branch rather than from a config file.
    # See `DOCKER` and `GITHUB_ACTIONS` above: the two vocabularies agree for one and disagree for
    # the other, and a member nothing matches excludes nothing.
    excluded_ecosystems: frozenset[str]
    # A TIGHTENING over the workflow this replaces, which required nothing -- branch protection is
    # `strict: false` estate-wide, deliberately. It is warranted here for a reason about `main`
    # rather than about production: a squash of a behind head produces a tree nothing executed,
    # and `main` is what every build session branches from. It is also what SERIALISES this lane,
    # which is why no pace condition accompanies it -- see the rationale.
    require_head_current_with_base: bool
    rationale: str

    # ADR-0041 (orchestrator). The permitted authors whose pull requests are NOT ecosystem-scoped.
    # An upstream sync is somebody else's release wholesale, not a dependency bump, so "which
    # package ecosystem" is the wrong question rather than one its branch failed to answer -- and
    # the landing party refused such a subject `landing_ecosystem_unreadable` until that ADR.
    #
    # DEFAULTED HERE AND OPTIONAL THERE, deliberately and for the same reason. Every other field in
    # this block BOUNDS what may land, so an absent one is a permission nobody granted. This one
    # EXEMPTS: empty means nobody is exempt, means every subject must produce a readable ecosystem,
    # which is the behaviour before the field existed. `inert_landing_dict` therefore omits the key
    # when it is empty, so version 6 serves exactly the bytes it always served.
    non_ecosystem_authors: frozenset[str] = frozenset()


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
    # ADR-0038. The OTHER population and its terms, or None for every version that predates the
    # question. It defaults to None for the same reason `rollout_workflows` defaults to empty and
    # `excluded_ecosystems` to None -- so the dataclass can gain a field while every superseded
    # version below stays readable exactly as it was decided.
    #
    # A version declaring none is NOT a version that opened this lane to nobody in particular: it
    # is one that did not decide the question at all. The landing party must read an absent block
    # as "this document names no inert population" and land nothing under it, which is the same
    # fail-closed reading `rollout_workflows` asks for and the opposite of the one an empty
    # `excluded_ecosystems` would get.
    inert_landing: InertLanding | None = None


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

# Every version ever, retained. A record stores the number that approved it, so an approval stays
# re-evaluable after the policy has moved on.
REGISTRY: Final[dict[int, DeployPolicy]] = {
    policy.version: policy for policy in (V1, V2, V3, V4, V5, V6, V7)
}

CURRENT_VERSION: Final = 7


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


def inert_landing_dict(policy: DeployPolicy) -> dict | None:
    """The inert population and its terms, or None for a version that declares none.

    None means the KEY IS OMITTED rather than served empty, for the reason
    `landing_conditions_dict` omits `excluded_ecosystems` one field over. A block declaring no
    repositories, nothing excluded and freshness false would tell a reader that versions 1 to 5
    considered this lane and admitted nobody to it. They considered nothing. An absent key says
    the version does not decide the question, which is what a landing party must fail closed on --
    and the two readings differ for exactly the versions that predate the field.
    """
    inert = policy.inert_landing
    if inert is None:
        return None
    served_inert: dict = {
        "repositories": sorted(inert.repositories),
        "permitted_authors": sorted(inert.permitted_authors),
        "excluded_ecosystems": sorted(inert.excluded_ecosystems),
        "require_head_current_with_base": inert.require_head_current_with_base,
        "rationale": inert.rationale,
    }
    # OMITTED WHEN EMPTY, so a version that declares no exemption serves the bytes it always
    # served. The reader treats absent and empty alike (ADR-0041), so this costs nothing and keeps
    # version 6's projection unchanged by a field it never decided.
    if inert.non_ecosystem_authors:
        served_inert["non_ecosystem_authors"] = sorted(inert.non_ecosystem_authors)
    return served_inert


def policy_dict(policy: DeployPolicy) -> dict:
    """The served shape of a policy version, built ONCE for both routes that serve it.

    ADR-0038 gave this document a second route, because the party that lands cannot spell the
    first one -- its architecture guards forbid the bare token that path is spelled with anywhere
    under its source tree, and its own rule is to reword rather than to widen a guard, which a URL
    cannot be. The two routes are two PROJECTIONS of one holder, and that is only true while they
    resolve through the same `current()` and this builder. Two routes composing their own bodies
    would be the second holder this module's header exists to prevent.

    It is here rather than beside the routes so that the omission below can be asserted over every
    retained version. A route only ever serves `current()`, so a test through the routes cannot
    reach a version that declares no inert population -- which is exactly the case the omission is
    for.
    """
    served = {
        "version": policy.version,
        "decided": policy.decided,
        "rationale": policy.rationale,
        "repositories": sorted(policy.repositories),
        "change_classes": sorted(policy.change_classes),
        "risks": sorted(policy.risks),
        "landing": landing_conditions_dict(policy),
    }
    # ADR-0038. THE KEY IS OMITTED BY A VERSION THAT DECLARES NO INERT POPULATION, and its
    # presence is what tells the landing party it has a second lane at all. The reason an empty
    # block is the wrong answer is on `inert_landing_dict`; this is where that None becomes an
    # absent key rather than a null one, because a reader that keys on presence must not be handed
    # a key whose value it then has to interpret.
    inert = inert_landing_dict(policy)
    if inert is not None:
        served["inert_landing"] = inert
    return served
