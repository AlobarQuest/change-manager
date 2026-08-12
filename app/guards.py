"""Refusals that must read the same at every door.

Both of these guard a *proposed* change (ADR-0019), and both have to be reachable from the
API router and from the GUI. They live here rather than in either one because the two doors
diverging is exactly the defect this module exists to prevent: increment 5's review found
`hand_off` guarded on the API and open in the GUI, where the button was merely hidden.

A hidden button is not a closed door. This repository has written that down twice.
"""

from fastapi import HTTPException

from app.models import ChangeItem
from app.sources import PROPOSED_SOURCES


def require_executor(it: ChangeItem) -> None:
    """Refuse every door into the EXECUTION lifecycle for a proposed change.

    The window executor makes THREE calls, not two -- it lists, claims, and then posts an
    outcome (`run-window.ts` getApproved/claim/postOutcome, and `security-executor.ts`
    likewise). Guarding only `claim` leaves `outcome` reachable on an unclaimed item, which
    writes a `ChangeAttempt` and an `attempt_done` event asserting that an agent applied a
    deploy nothing performed -- and that event ships to the tamper-evident factory-events
    chain. `outcome` is unreachable in practice only because the executor skips an item
    whose claim failed, and "unreachable because its only caller checks first" is not a
    property a future caller inherits.
    """
    if not it.has_authorized_executor:
        raise HTTPException(
            status_code=409,
            detail=f"'{it.source}' changes have no authorized executor (item {it.id})",
        )


def require_policy_approver(it: ChangeItem) -> None:
    """Refuse APPROVAL of a proposed change to every caller, whatever bearer it holds.

    ADR-0019 increment 5. A deploying-merge record is approved by conformance to a pinned,
    versioned policy and by nothing else (`deploy_changes._apply_policy`), so there is no
    approval here for a caller to perform. Devon's ruling is that the human act is setting
    the policy, not deciding a change one at a time -- and a door that still accepted an
    individual approval would make that ruling advisory.

    This is deliberately WIDER than the credential split increment 4 shipped. That made the
    producer unable to approve; this makes the FULL bearer unable to, and the GUI too. The
    remaining human powers over such a record are the vetoes -- defer, wontfix, resolve --
    and reactivate, which is the asymmetry Devon asked for: policy grants, a human revokes.

    The other four decisions stay open on purpose. A record whose pull request is closed
    must still be closable, or the queue accumulates rows nobody can retire.

    This is the readable refusal; the guarantee is in `transitions.decide`, on the write,
    where every caller reaches it whether or not it remembered to.
    """
    if it.source in PROPOSED_SOURCES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"'{it.source}' changes are approved by policy conformance, not by a caller "
                f"(item {it.id}); a human ratifies them by setting the policy"
            ),
        )
