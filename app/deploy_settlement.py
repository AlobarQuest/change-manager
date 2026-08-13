"""Settle a deploying-merge record whose landing succeeded (ADR-0022).

A record proposed for a pull request that LANDED, and whose rollout production confirmed, stands
for a change that has already happened. Nothing settles it, so an approved record sits in the
estate authorising a landing that is done — the mirror image of the closed-unmerged case
`app/deploy_retirement.py` closes, and the half nobody had. Production item 52 is the live case:
`alobarquest/change-manager` #50 merged, its rollout went green, the watcher recorded
`verdict=success production_reached=yes attests=revision_confirmed` twenty minutes later, and the
record stayed `approved`.

WHY THE WATCHER AND NOT THE PRODUCER. ADR-0022. The producer's remit is what MAY happen; the
watcher's is what DID. The watcher already holds the fact, and giving the closure to the producer
would put two components on GitHub reading the same thing for the same purpose, with the weaker of
the two ruling. The producer's own retirement sweep sees a merged pull request and reports
`skipped`, deliberately.

WHY THIS IS NOT A ROUTE OF ITS OWN, where retirement is. Retirement acts on a fact only the CALLER
can see — GitHub says this pull request closed unmerged — so it needs a door through which that
fact can be declared. A settlement acts on a fact THIS SERVER DERIVED: `verdict` and
`production_reached` are computed here from coordinates the caller supplied and are not accepted
as fields. So there is nothing for a caller to say, and a route on which to say it would be a route
that takes a status.

WHY IT MAY MOVE A STATUS AT ALL, and why that is narrower than it looks. The same direction
argument retirement makes: the only outcome is `resolved`, which no landing term accepts, so this
can remove permission and can never grant it.

**BE EXACT ABOUT THE SECONDARY ARGUMENT, because a first draft was not.** It also said the fact is
not the caller's, since `deploy_watcher recheck` re-derives it from GitHub — and `workflow_
attestation`, the field the strong-form clause below rests on, was *absent* from what that command
compared. It is caller-supplied and unvalidated here (`app/schemas.py` declares a bare `str`), and
it additionally decides `classified` in `production_reached_for`, so one string unlocked two of the
three clauses while nothing re-derived it. ADR-0022 added it to the re-check, which is one line and
which the claim needed. Read the property as **detection, hourly, after the fact** — never as
prevention: this service has no GitHub egress and cannot check anything at the moment of the write.

THE STRONG FORM IS REQUIRED, AND THAT IS THE ONE JUDGMENT HERE. `revision_confirmed` means
production was asked and reported the merged commit. `rollout_unverified` means a green run proved
a webhook answered, or that a domain was up while Coolify's rolling swap was still serving the OLD
container — which is the overstatement this estate has already measured and killed once. A record
settled on that would assert a change succeeded on evidence the estate has written down as unable
to establish it. So a repository whose rollout does not verify the revision accumulates records
that a person must close, and that is the correct outcome rather than a gap: those rollouts really
do not say what a settlement would claim. Today that is `alobarquest/brain` and every
`alobarquest/change-manager` revision before `a47d4b18`.

SETTLE ON A FACT, NEVER ON ABSENCE. "The reduced observation says the merged build is what
production reported" settles a record. An unreadable rollout, an unclassified workflow revision, a
history that disagrees with itself about which landing it describes — none of them settle anything,
and each leaves the record exactly where it was.

NOTHING HERE UN-SETTLES. A rollout that fails after a record has settled is recorded (the
observation table is append-only) and the status is left alone: reopening is a decision, and this
module records outcomes. The contradiction is REPORTED instead, by the watcher, which is the party
that can see it.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.deploy_observations import (
    REACHED_YES,
    VERDICT_SUCCESS,
    current_observation,
    observations_for,
    record_deploy_observation,
)
from app.events import record_event
from app.models import ChangeItem, DeployObservation
from app.schemas import DeployObservationIn
from app.sources import DEPLOY_SOURCE

# The attestation level under which a green rollout means the merged build is what production
# reported. Mirrored from `deploy_watcher.workflows.ATTESTS_REVISION`, which is the party that
# transcribes it; this service has no GitHub egress and cannot derive it.
ATTESTS_REVISION = "revision_confirmed"

# Already terminal. `resolved` is a settlement or a retirement that has already happened;
# `wontfix` is a human deciding against the change, and a machine overriding that would be the
# machine re-deciding rather than recording. Mirrors `deploy_retirement._TERMINAL` exactly, so the
# two ways a deploy record can be closed agree about what is already closed.
_TERMINAL = frozenset({"resolved", "wontfix"})

SETTLED_STATUS = "resolved"
SETTLED_EVENT = "settled"

# The actor recorded against the settlement. It names the MECHANISM rather than a person or a
# credential, exactly as `deploy_changes.POLICY_ACTOR` does: what decided is an observation this
# server reduced, and `actor` on a change-manager decision is caller-declared free text, so a
# caller-supplied name here would attest nothing.
SETTLEMENT_ACTOR = "rollout-observation"


def landed_successfully(observation: DeployObservation | None) -> bool:
    """Does the reduced observation say the change landed and production is serving it?

    Every clause is a positive check on a value this server derived. `None` — no observation, or a
    history that names more than one merge commit and therefore has no single answer — is not a
    weak yes; it is the absence this module refuses to act on.
    """
    if observation is None:
        return False
    return (
        observation.verdict == VERDICT_SUCCESS
        and observation.production_reached == REACHED_YES
        and observation.workflow_attestation == ATTESTS_REVISION
    )


def settle_landed_deploy_change(db: Session, item: ChangeItem) -> bool:
    """Settle the record if its rollout confirmed. Returns whether it moved. We commit.

    Reads the reduction from `current_observation` rather than from whichever row the caller just
    wrote, and the difference is the point: a re-run that supersedes a success is a later, higher
    attempt, and the reduction is where this service already decides which row answers "how did the
    rollout go?". A settlement computed from the arriving row would answer a different question on
    a second attempt than the detail page does.

    It is a SEPARATE TRANSACTION from the observation's append, deliberately. The alternative is
    atomicity; what this buys instead is convergence, which is what is actually needed here — the
    settlement runs on every path into this function including a replay, so a pass interrupted
    between the two commits settles on the next one. Production item 52 is that case already: its
    observation was recorded before this code existed, so a REPLAY is the only route by which it
    can ever settle, and a settlement reachable only from the created path would never touch it.
    """
    if item.source != DEPLOY_SOURCE:
        return False
    if item.status in _TERMINAL:
        return False
    if not landed_successfully(current_observation(observations_for(db, item.id))):
        return False

    prev = item.status
    item.status = SETTLED_STATUS
    # `decided_by` is a latest-writer column by decision (Devon, 2026-08-12): it answers who is
    # answerable for the record's current state, and `change_events` answers how it got there.
    item.decided_by = SETTLEMENT_ACTOR
    item.decided_at = datetime.now(UTC)
    record_event(
        db,
        item,
        actor=SETTLEMENT_ACTOR,
        event_type=SETTLED_EVENT,
        from_status=prev,
        to_status=SETTLED_STATUS,
        detail=(
            f"{item.target_repository}#{item.pull_request_number} landed and its rollout was "
            f"observed to succeed with production reporting the merged commit; settled against "
            f"that observation rather than by any caller's decision"
        ),
    )
    db.commit()
    return True


def record_rollout_and_settle(
    db: Session, item: ChangeItem, body: DeployObservationIn
) -> tuple[DeployObservation, bool, bool]:
    """Append the observation, then settle the record if it now settles. Returns (row, created,
    settled).

    THE COMPOSITION LIVES HERE SO NO CALLER HAS TO REMEMBER IT. Every path into
    `record_deploy_observation` -- a new row, a replay of the same facts, the loser of a race --
    must be followed by the settlement check, because the reduction it consults is a property of
    the whole history rather than of the row this call happened to write. Two of those three paths
    write nothing at all, and the replay is the one production item 52 needs. A route that called
    the two functions in sequence would be correct today and would be a door a second caller does
    not inherit, which is the shape this repository has already been bitten by twice; a test asserts
    that `app.api` reaches the appender only through here.
    """
    observation, created = record_deploy_observation(db, item, body)
    return observation, created, settle_landed_deploy_change(db, item)
