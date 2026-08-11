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
    }
)

# The scopes a narrow credential may hold. Each is READ plus at most one write, and no write here
# touches the DECISION lifecycle (approve/defer/wontfix/resolve/reactivate) or the EXECUTION one
# (claim/outcome/handoff). That is the whole point of the file.
SCOPE_ROUTES: Final[dict[str, frozenset[tuple[str, str]]]] = {
    READ: _READ_ROUTES,
    PROPOSE: _READ_ROUTES | {("POST", "/api/deploy-changes")},
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
    }
)
