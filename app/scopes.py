"""What each machine credential may reach, keyed on (method, route template).

ADR-0019 increment 4, task zero. Until now one static bearer covered the whole `/api` router, so
the credential that READS a change record could also APPROVE one. That was a bound rather than a
breach only because nothing proposed records; increment 4 ships the first producer of them. A
producer holding a credential that can approve its own proposal is a system asking itself for
permission, so **the split has to exist before the producer does** — afterwards is too late for
the property to have ever held.

**Anything not listed here requires the full credential.** The unknown case therefore refuses for
every narrow scope: a route added later is reachable only by the full bearer until somebody
decides otherwise. That direction is deliberate — a new door should not open itself to a machine.

**METHOD is part of the key, and that is not fussiness.** `GET` and `POST` on
`/api/items/{item_id}/handoff` are the SAME template: one reads a handoff brief, the other drives
the execution lifecycle. A template-only allowlist that permitted the read would hand over the
write with it. The orchestrator's `_confine_observer`, which this shape is modelled on, is safe
without that distinction only because it exempts reads wholesale and confines exactly one write;
this surface has no such property, so the analogy is followed in structure and not in detail.

**`read` is an enumerated list, not "every GET".** Two GET routes are deliberately outside it:
`/api/items/{item_id}/handoff` serves handoff briefs, which are instructions written for an agent
holding production infrastructure tools, and no narrow consumer needs them.
"""

from typing import Final

FULL: Final = "full"
READ: Final = "read"
PROPOSE: Final = "propose"
OBSERVE: Final = "observe"

# Reading a change record. Held by the orchestrator's admission term (ADR-0019 increment 3) and,
# with one write added below, by the rollout watcher (increment 2).
_READ_ROUTES: Final = frozenset(
    {
        ("GET", "/api/items"),
        ("GET", "/api/items/{item_id}"),
        ("GET", "/api/items/{item_id}/deploy-observations"),
        ("GET", "/api/events"),
        # What a human has pre-approved, and the conditions the landing party must evaluate
        # because this service cannot (ADR-0019 increment 5). Standing policy, no secret,
        # and a caller that could not read it could only fail closed.
        ("GET", "/api/deploy-policy"),
    }
)

# The scopes a narrow credential may hold. Each is READ plus the writes named below, and no write
# here lets the CALLER CHOOSE a record's status: the DECISION lifecycle
# (approve/defer/wontfix/resolve/reactivate) and the EXECUTION one (claim/outcome/handoff) are
# both out of reach. That is the whole point of the file.
#
# CORRECTED BY ADR-0019 INCREMENT 5a. This used to say no write here "touches the DECISION
# lifecycle", and that became false the moment the proposal ingress started running the deploy
# policy: `propose` can now cause a record to be approved. It cannot pick that outcome — policy
# decides, over a shape a human pinned in advance — which is a real and narrower property, and
# saying the old sentence instead would have left the one file whose subject is "which credential
# can move a status" giving the wrong answer.
SCOPE_ROUTES: Final[dict[str, frozenset[tuple[str, str]]]] = {
    READ: _READ_ROUTES,
    PROPOSE: _READ_ROUTES
    | {
        ("POST", "/api/deploy-changes"),
        # ADR-0026. Proposing work for the delivery system. It is here with the deploy proposal
        # because it is the same act -- a caller asserting a change it wants made -- and it is
        # STRICTLY WEAKER than that one: the deploy ingress runs the policy and can therefore
        # write `approved`, while this route creates a `pending` record and can reach no other
        # status. A human approves it, which is the property ADR-0026 decision 5 rests on and
        # the reason this entry is not also in `STATUS_MOVING_ROUTES` below.
        ("POST", "/api/work-changes"),
        # ADR-0019 increment 5b. The producer that enumerates pull requests waiting to happen is
        # the only thing positioned to see one CLOSED without merging, and a record standing for a
        # change that can never happen is the hole increment 5b closes. It is here rather than as
        # a general `resolve` -- which stays the full credential's -- because this route takes a
        # fact and not a status, works on deploy records only, and can reach exactly one outcome.
        ("POST", "/api/items/{item_id}/deploy-retirement"),
        # ADR-0029. The work source's success direction. It is here for the same three reasons
        # the deploying-merge retirement is -- a fact rather than a status, one source only, one
        # reachable outcome -- and it is here rather than in a scope of its own because a fourth
        # scope would be a credential nobody holds until somebody mints it, while the property
        # that matters is asserted per MODULE: each program allowlists the paths it may reach, so
        # holding this scope is not the same as being able to use all of it.
        ("POST", "/api/items/{item_id}/work-retirement"),
    },
    OBSERVE: _READ_ROUTES | {("POST", "/api/items/{item_id}/deploy-observation")},
}

NARROW_SCOPES: Final = tuple(SCOPE_ROUTES)

# Routes by which a change record's status can move, or by which an executor can assert it acted.
# Named here as data so a test can state the property in ROW terms rather than trusting that a
# list of route strings happens to cover it -- increment 1's kill was a guard keyed on the right
# concept and the wrong field, and the lesson generalises to this file.
STATUS_MOVING_ROUTES: Final = frozenset(
    {
        ("POST", "/api/items/{item_id}/approve"),
        ("POST", "/api/items/{item_id}/defer"),
        ("POST", "/api/items/{item_id}/wontfix"),
        ("POST", "/api/items/{item_id}/resolve"),
        ("POST", "/api/items/{item_id}/reactivate"),
        ("POST", "/api/items/{item_id}/claim"),
        ("POST", "/api/items/{item_id}/outcome"),
        ("POST", "/api/items/{item_id}/handoff"),
        ("POST", "/api/sync"),
        # ADR-0019 increment 5a. The proposal ingress MOVES A STATUS, and saying otherwise is
        # what this entry exists to stop. `propose_deploy_change` runs the deploy policy on both
        # a new record and an existing one, so it can write `approved` and it can revoke back to
        # `pending`. Until increment 5a it genuinely could not touch a stored row; the module
        # docstring above, and this set, both said so, and both would have gone on saying so.
        ("POST", "/api/deploy-changes"),
        # ADR-0019 increment 5b. Retirement moves a status to `resolved`. It belongs here even
        # though the caller never names that status -- this set is about what MOVES, and the set
        # below is about what a caller may CHOOSE.
        ("POST", "/api/items/{item_id}/deploy-retirement"),
        # ADR-0029. The work source's retirement, and it moves a status for the same reason.
        ("POST", "/api/items/{item_id}/work-retirement"),
        # ADR-0026. The work-proposal ingress. It is here on the CONSERVATIVE reading, and the
        # conservative reading is the one this file's own history argues for: today the route
        # writes a `pending` record and a repeat is a pure no-op, so an exclusion claiming "it
        # cannot write to an existing row" would be true -- and that is word for word the claim
        # the deploy ingress carried until increment 5a falsified all three of its clauses, and
        # the shape the observation ingress carried until ADR-0022 falsified its. An exclusion
        # is a claim about behaviour, and this one would be a claim about behaviour that has not
        # been built yet. Listing it costs nothing while the claim holds and is already correct
        # if a policy is ever given to this pipeline.
        ("POST", "/api/work-changes"),
        # ADR-0022. Recording a rollout observation settles the record when the rollout confirmed
        # the change landed, so this route moves a status too -- and until that ADR it did not,
        # which is exactly why it has to be added here rather than left reading correctly by
        # accident. `app/deploy_settlement.py` carries the argument for why an `observe`
        # credential may cause it.
        ("POST", "/api/items/{item_id}/deploy-observation"),
    }
)

# The narrower property that is still TRUE of every narrow credential, and the one worth
# guarding: none of them can CHOOSE a record's status.
#
# The distinction is the whole of ADR-0019 increment 5a. A `propose` credential can cause a
# status to move, because proposing a record whose shape conforms to a pinned policy is what
# approval IS -- but it cannot select the outcome, cannot approve a record it did not propose,
# and cannot approve one whose shape a human has not ratified in advance. Every other
# status-moving route takes the new status from the caller.
#
# Increment 5b adds the second, and the two are the same shape: retirement takes an OBSERVATION
# and the server decides what follows, so the caller cannot pick `resolved` any more than it can
# pick `approved`. It is additionally one-directional in a way proposal is not -- its only outcome
# removes permission -- which is why it may act on a fact this service cannot check.
#
# ADR-0022 adds the third, and it is the narrowest of them. Retirement acts on a fact only the
# CALLER can see, so it has to be trusted with it; a settlement acts on a verdict THIS SERVER
# DERIVED from coordinates, which `verdict_for` and `production_reached_for` compute and which the
# schema refuses to accept as fields. Its outcome is one-directional in the same way retirement's
# is: `resolved` is a status no landing term accepts.
#
# Stated as a subtraction from the set above rather than as its own literal, so a route added to
# one is added to both and the exceptions stay exactly the three entries named here.
#
# ADR-0026 adds the fourth, and it is the only one that is narrow by CONSTRUCTION rather than by
# derivation. The other three compute an outcome the caller cannot pick; this one cannot compute
# anything -- `status="pending"` is a literal in the constructor and the route has no other write,
# so the set of statuses reachable through it has one member and that member is the one every
# record starts at. A human approves it afterwards, through the ordinary decision routes, which is
# the property ADR-0026 decision 5 rests on.
#
# ADR-0029 adds the fifth, and it is the second copy of the retirement shape rather than a new
# one: an observation in, a status the server picks, one reachable outcome that only ever removes
# permission. What is new is that the work source's SUCCESS direction is retirement-shaped, where
# the deploy source's is a settlement -- because a settlement needs the deciding server to derive
# the fact, and this one has no orchestrator egress and cannot.
CALLER_CHOSEN_STATUS_ROUTES: Final = STATUS_MOVING_ROUTES - {
    ("POST", "/api/deploy-changes"),
    ("POST", "/api/items/{item_id}/deploy-retirement"),
    ("POST", "/api/items/{item_id}/deploy-observation"),
    ("POST", "/api/work-changes"),
    ("POST", "/api/items/{item_id}/work-retirement"),
}
