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

WHERE A SUPERSEDED VERSION GOES. This module holds only the version in force and the terms it still
carries; versions 1 to 8 live verbatim in `app.deploy_policy_history`, with `REGISTRY` and
`policy_for`. A bump moves the outgoing version there unedited, keeps here any term the new version
still carries (named for the version that introduced it), and has the history module import that
term rather than copy it. The import runs one way, history to this module, so nothing a live path
reads can depend on a superseded version.

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

import json
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
# Terms introduced by a superseded version and still in force under the current one.
# ---------------------------------------------------------------------------
#
# Each is named for the version that introduced it. The versions themselves -- 1 to 8 -- are
# retained verbatim in `app.deploy_policy_history`, which imports these rather than holding a
# second transcription of one judgment.

# Introduced by version 1.
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

# Introduced by version 3.
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

# Introduced by version 5.
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

# Introduced by version 7.
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

# ---------------------------------------------------------------------------
# Version 8 -- the version in force.
# ---------------------------------------------------------------------------

# brain#62, 2026-09-07. The SECOND criterion moved and the first did not: the rollout still
# concludes at the same job and step, and what a green run now attests is strictly more. The
# workflow reads `deployments[0].deployment_uuid` out of each trigger response and fails the step
# when it is absent, so a 2xx that queued nothing no longer counts as a trigger; and it asks
# Coolify for that deployment's status before each revision poll, so an explicit `failed` fails
# the run in about forty seconds rather than at the 600-second deadline.
#
# RATIFIED RATHER THAN TRANSCRIBED, which is the whole point of this constant existing separately
# from version 3's. The producer derives this text from the workflow's bytes; a human reading the
# diff decides whether the remedy pinned beside it is still the right remedy. It is: the rollback
# is unchanged, because failing earlier and failing on a fact that was previously invisible do not
# change how production is put back.
_V8_BRAIN_CRITERIA: Final = (
    "the rollout runs for this merge on alobarquest/brain, and its production step concludes "
    "success (job 'deploy', step 'Deploy brain apps')",
    "every brain application this rollout triggered answered /api/health reporting the merged "
    "commit as its revision and a status of ok, within 600 seconds, and Coolify named a "
    "deployment for each one it was asked to deploy; a trigger whose 2xx response names no "
    "deployment fails the rollout rather than counting as queued, and a deployment Coolify "
    "itself reports as failed fails the run at once rather than at the deadline; an application "
    "whose Coolify UUID secret is unset is neither triggered nor checked, and a rollout that "
    "triggered none fails rather than passing empty",
)


# THE SAME TERMS ON THE ACT VERSION 5 DECIDED, with BOTH repositories' rollouts re-pinned. Both
# workflows moved for one reason, the Python 3.14 move (brain#77, change-manager#99), and
# neither move touches what a green rollout proves:
#   - brain's `ci.yml` changed only its `test` job, whose setup-python now reads .python-version.
#     The `deploy` job, its trigger step and its verify step are byte-identical to `7cf6ca2d`.
#   - change-manager's `deploy.yml` changed its `test` job the same way, and gained a
#     setup-python step at the head of `build-and-deploy`, so the verify step's `python3` is the
#     pinned interpreter rather than the runner image's. The trigger and verify steps are
#     byte-identical to `a47d4b18`.
# So the criteria each pin sits beside are the ones already ratified, unedited.
_V9_LANDING: Final = LandingConditions(
    update_types=_V5_LANDING.update_types,
    require_head_current_with_base=_V5_LANDING.require_head_current_with_base,
    excluded_ecosystems=_V5_LANDING.excluded_ecosystems,
    rationale=(
        _V5_LANDING.rationale + " VERSION 9 RE-PINS BOTH ROLLOUTS -- brain at `2017c1ed`, "
        "change-manager at `b92f812c` -- after the Python 3.14 move edited each workflow's "
        "setup steps. What either rollout proves has not moved. Nothing else about the act "
        "changes."
    ),
    rollout_workflows={
        "alobarquest/change-manager": WorkflowPin(
            path=".github/workflows/deploy.yml",
            # Supersedes `a47d4b18`, which versions 3 to 8 pinned.
            blob_sha="b92f812ccb036027d4bc8682405ab092ec32eb17",
        ),
        "alobarquest/brain": WorkflowPin(
            path=".github/workflows/ci.yml",
            # Supersedes `7cf6ca2d`, which version 8 pinned.
            blob_sha="2017c1ed0fcfbb844d2b933c542c9a5f29a1f17a",
        ),
    },
)


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


CURRENT_VERSION: Final = 9


def current() -> DeployPolicy:
    return V9


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


# The committed projection below, for a party that must compare against it and may not run this
# module. The orchestrator derives a record's acceptance criteria and rollback plan, and
# `objections` compares them byte for byte against the CURRENT version; before this existed the
# two sides each pinned a literal of their own, and on 2026-09-27 those literals were two versions
# apart with both suites green. The other side reads the JSON as DATA over the contents API --
# it never imports or executes this file -- so the projection is committed rather than computed
# on request, and `tests/test_ratified_rollout_policy.py` holds the committed bytes to this
# function so the file cannot drift from the code.
RATIFIED_ROLLOUT_POLICY_PATH: Final = "contracts/ratified_rollout_policy.json"
RATIFIED_ROLLOUT_SCHEMA_VERSION: Final = 1


def ratified_rollout_dict(policy: DeployPolicy) -> dict:
    """What a record for each ratified repository must carry under `policy`, and the rollout pin.

    Keyed by repository. A repository with ratified criteria but no rollout pin cannot occur in a
    version this module accepts, and is refused here rather than projected as a pin-less entry a
    reader might take for a waiver.
    """
    repositories: dict = {}
    for repository, criteria in sorted(policy.acceptance_criteria.items()):
        pin = policy.landing.rollout_workflows.get(repository)
        if pin is None:
            raise ValueError(f"{repository} has ratified criteria and no rollout pin")
        repositories[repository] = {
            "rollout_workflow": {"path": pin.path, "blob_sha": pin.blob_sha},
            "acceptance_criteria": list(criteria),
            "rollback_plan": policy.rollback_plans[repository].as_stored(),
        }
    return {
        "schema_version": RATIFIED_ROLLOUT_SCHEMA_VERSION,
        "policy_version": policy.version,
        "repositories": repositories,
    }


def render_ratified_rollout_policy(policy: DeployPolicy) -> str:
    """The exact bytes committed at RATIFIED_ROLLOUT_POLICY_PATH: sorted keys, two-space indent."""
    return json.dumps(ratified_rollout_dict(policy), indent=2, sort_keys=True) + "\n"
