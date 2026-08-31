"""The credential split (ADR-0019 increment 4, task zero).

The property this file exists to establish, in one sentence: **no narrow credential can approve a
change record.** Increment 3's admission term reads those records, increment 4 ships the first
producer of them, and a producer holding a credential that could also approve its own proposal
collapses the whole control into a system asking itself for permission.

Two of these tests are written over the LIVE route table rather than over a hand-kept list,
because a list is a second copy that goes stale. Getting that enumeration right took two attempts
and the failure mode of the first one is the interesting part — see `_api_routes`.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scopes import (
    CALLER_CHOSEN_STATUS_ROUTES,
    NARROW_SCOPES,
    OBSERVE,
    PROPOSE,
    SCOPE_ROUTES,
    STATUS_MOVING_ROUTES,
)

FULL_TOKEN = "full-tok"
TOKENS = {"read": "read-tok", "propose": "propose-tok", "observe": "observe-tok"}


@pytest.fixture()
def scoped() -> Iterator[None]:
    """Configure all four credentials, and put every one of them back afterwards."""
    import app.auth as auth

    before = (
        auth.settings.m2m_token,
        auth.settings.m2m_token_read,
        auth.settings.m2m_token_propose,
        auth.settings.m2m_token_observe,
    )
    auth.settings.m2m_token = FULL_TOKEN
    auth.settings.m2m_token_read = TOKENS["read"]
    auth.settings.m2m_token_propose = TOKENS["propose"]
    auth.settings.m2m_token_observe = TOKENS["observe"]
    yield
    (
        auth.settings.m2m_token,
        auth.settings.m2m_token_read,
        auth.settings.m2m_token_propose,
        auth.settings.m2m_token_observe,
    ) = before


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _api_routes() -> list[tuple[str, str]]:
    """Every (method, template) the APPLICATION serves under /api, from the OpenAPI schema.

    **Not from `app.routes`, and the reason is a trap worth recording.** This FastAPI version
    nests an included router as a single `fastapi.routing._IncludedRouter` entry rather than
    flattening its routes into `app.routes`, so the obvious walk — filter `app.routes` for
    `APIRoute` — sees exactly ONE route here (`/api/health`, the only one registered directly on
    the application) and silently reports the entire `/api` surface as absent. A completeness
    test built that way asserts nothing while looking thorough; this one failed loudly only
    because `test_every_status_moving_route_is_a_route_this_app_actually_serves` cross-checks the
    enumeration against a set of routes known to exist.

    `app.openapi()["paths"]` is flattened, authoritative, and is what the orchestrator's own scope
    guards enumerate. It still sees `/api/health`, which is the case `api.router.routes` misses.
    """
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path.startswith("/api")
        for method in operations
    )


# --- the property, stated the two ways that matter -------------------------------------------


@pytest.mark.parametrize("scope", NARROW_SCOPES)
def test_no_narrow_scope_can_choose_a_change_records_status(scope: str) -> None:
    """Stated in ROW terms, not route terms.

    Increment 1's kill was a guard keyed on the right concept and the wrong field. The route list
    is only today's spelling of the property; what must be true is that no narrow credential can
    CHOOSE a record's status or assert that something executed it.

    RENAMED BY ADR-0019 INCREMENT 5a, and the old name is the point. It was
    `..._can_move_a_change_records_status`, and "move" became false the moment the proposal
    ingress started running the deploy policy: `propose` reaches the one route that can put a
    record into `approved`. Stage-two review found the module docstring and the exclusion comment
    still asserting the old sentence; the test's own name and docstring were asserting it too, one
    file over from the finding. A name is a claim.
    """
    assert not (SCOPE_ROUTES[scope] & CALLER_CHOSEN_STATUS_ROUTES), (
        f"the '{scope}' scope reaches {sorted(SCOPE_ROUTES[scope] & CALLER_CHOSEN_STATUS_ROUTES)}"
    )


@pytest.mark.parametrize("scope", NARROW_SCOPES)
def test_the_status_moving_routes_a_narrow_scope_reaches_are_named_and_bounded(scope: str) -> None:
    """The exception is NAMED and exactly enumerated, so it cannot silently grow.

    ADR-0019 increment 5a: `propose` reaches the proposal ingress, and that ingress runs the
    deploy policy — so it CAN cause an approval. The guard above is keyed on the narrower
    property that survives (no narrow credential picks a status). This one bounds the gap, so
    that a third status-moving route landing in a narrow scope is a failure rather than a
    quietly widened exception.

    Increment 5b adds the retirement ingress to the same scope. It is the same shape — a fact in,
    a server decision out — with one property proposal does not have: its only outcome REMOVES
    permission, which is what makes it acceptable on an observation this service cannot check.

    ADR-0022 gives `observe` its first one, and it is the narrowest of the three: the observation
    ingress settles a record whose rollout production confirmed, on a verdict this server derived
    rather than on anything the caller said. `read` still reaches none, which is the control —
    without it this test would pass on a table that had quietly given every narrow scope a
    status-moving route.

    ADR-0026 gives `propose` a third, and it broke this test's old NAME rather than its property:
    the work-proposal ingress moves no status a policy decides, because no policy governs it. It
    writes a `pending` record, and `pending` is where every record already starts. The name is a
    behavioural claim, which this module records having learnt twice, so it moved with the
    behaviour.

    ADR-0029 gives `propose` a fourth, and it is the first REPEAT of a shape rather than a new
    one: the work source's retirement is the deploying-merge retirement one source over. What is
    worth noticing is that it closes the SUCCESS direction, which for the deploy source is a
    settlement needing no route at all -- the shapes diverge because a settlement requires the
    deciding server to derive the fact, and this one has no orchestrator egress.
    """
    reached = SCOPE_ROUTES[scope] & STATUS_MOVING_ROUTES
    expected = {
        PROPOSE: {
            ("POST", "/api/deploy-changes"),
            ("POST", "/api/items/{item_id}/deploy-retirement"),
            ("POST", "/api/work-changes"),
            ("POST", "/api/items/{item_id}/work-retirement"),
        },
        OBSERVE: {("POST", "/api/items/{item_id}/deploy-observation")},
    }.get(scope, set())
    assert reached == expected, f"the '{scope}' scope reaches {sorted(reached)}"


def test_every_status_moving_route_is_a_route_this_app_actually_serves() -> None:
    """The guard above is worthless if it names routes that do not exist.

    A renamed or deleted route would silently shrink the set it protects, and the parametrized
    test above would keep passing while protecting less.
    """
    served = set(_api_routes())
    missing = STATUS_MOVING_ROUTES - served
    assert not missing, f"STATUS_MOVING_ROUTES names routes that do not exist: {sorted(missing)}"


def test_status_moving_routes_is_complete_against_the_live_table() -> None:
    """The literal cannot silently SHRINK, which existence-checking alone does not prevent.

    A mutation pass caught this: emptying `STATUS_MOVING_ROUTES` left both the row-terms guard and
    the existence check green, because an empty set trivially satisfies "intersects nothing" and
    "names nothing absent". A literal that states a judgment needs a derivation cross-check, or
    the judgment is pinned by nothing — the estate's own lesson from an eight-hop chain whose
    fixtures all derived themselves from the list they were meant to be checking.

    Every write under `/api` moves a change record's status EXCEPT those named below, and each
    exclusion is a claim about behaviour rather than a convenience.

    `POST /api/deploy-changes` was excluded here until ADR-0019 increment 5a, on the claim that it
    "never writes to an existing row -- identical facts replay, different facts 409". That claim
    had three clauses and the increment falsified all three: it refreshes the derived facts on an
    existing row, differing derived facts no longer 409, and it moves the status in both
    directions. An exclusion is a claim about behaviour, so it has to be re-read when the
    behaviour changes -- this one was green while the propose scope held the only route in the
    application that can put a record into `approved`.

    THE OBSERVATION INGRESS PROVED THE POINT A SECOND TIME. It was excluded here until ADR-0022, on
    the claim that it "moves status by exactly nothing" -- true when written, and false the moment
    a confirmed rollout began settling the record it describes. Same lesson, same file, one
    increment later: the exclusions are the part of this test that goes stale.
    """
    writes = {(method, path) for method, path in _api_routes() if method != "GET"}
    not_status_moving = {
        # Sets `pr_url` and records a `pr_linked` event. Not a status transition -- but it IS a
        # write, which is why `read` must not reach it (see the PATCH test below).
        ("PATCH", "/api/items/{item_id}"),
        # WindowRun, not ChangeItem.
        ("POST", "/api/window-runs"),
        ("PATCH", "/api/window-runs/{window_id}"),
    }
    assert STATUS_MOVING_ROUTES == writes - not_status_moving


def test_a_route_no_scope_lists_is_reachable_only_by_the_full_credential() -> None:
    """That the enumeration SEES the whole application — not that the scopes are correct.

    **This test does less than its first name suggested, and the difference matters.** `unlisted`
    is *defined* as the pairs not in the union of `SCOPE_ROUTES`, so looping over it to assert they
    are in no scope is a tautology: granting every narrow scope `POST /api/items/{id}/approve` was
    demonstrated to leave it green. What it genuinely asserts is the `/api/health` line — that this
    enumeration reaches routes registered on the APPLICATION rather than on the router, which is
    the blindness `_api_routes` documents.

    The scopes themselves are protected by `test_no_narrow_scope_can_move_a_change_records_status`
    and, derived from the live table so it cannot pass vacuously,
    `test_no_narrow_scope_reaches_any_write_except_the_three_they_exist_for`.
    """
    listed: set[tuple[str, str]] = set()
    for routes in SCOPE_ROUTES.values():
        listed |= routes
    unlisted = [pair for pair in _api_routes() if pair not in listed]

    assert ("GET", "/api/health") in unlisted
    for method, template in unlisted:
        for scope in NARROW_SCOPES:
            assert (method, template) not in SCOPE_ROUTES[scope]


def test_no_narrow_scope_reaches_any_write_except_the_four_they_exist_for() -> None:
    """Derived from the live table, so it cannot pass vacuously and cannot go stale.

    `test_no_narrow_scope_can_move_a_change_records_status` above is keyed on a LITERAL set, which
    is the right way to state a judgment — but a literal can be emptied, and an emptied set makes
    an intersection assertion pass while protecting nothing. This one computes the writes from the
    application itself and pins the intersection exactly, so emptying the literal changes nothing
    here, and a NEW write route added later is refused to every narrow scope until someone edits
    this line on purpose.
    """
    writes = {(method, path) for method, path in _api_routes() if method != "GET"}
    reachable: set[tuple[str, str]] = set()
    for routes in SCOPE_ROUTES.values():
        reachable |= routes

    assert reachable & writes == {
        ("POST", "/api/deploy-changes"),
        ("POST", "/api/items/{item_id}/deploy-observation"),
        ("POST", "/api/items/{item_id}/deploy-retirement"),
        # ADR-0026. The work-proposal ingress, reachable by `propose`. It is the same act as the
        # deploy proposal and strictly weaker: that one runs the policy and can write `approved`,
        # this one can reach `pending` and nothing else.
        ("POST", "/api/work-changes"),
        # ADR-0029. The work source's retirement, reachable by `propose` for the same three
        # reasons the deploying-merge one is.
        ("POST", "/api/items/{item_id}/work-retirement"),
    }


# --- and the same property, exercised through real HTTP requests ------------------------------


def test_the_propose_credential_cannot_approve(client: TestClient, scoped: None) -> None:
    """THE control this increment exists to make true."""
    response = client.post(
        "/api/items/1/approve", json={"actor": "producer"}, headers=_bearer(TOKENS["propose"])
    )
    assert response.status_code == 403
    assert "propose" in response.json()["detail"]


@pytest.mark.parametrize("scope", ["read", "propose", "observe"])
def test_no_narrow_credential_can_approve_over_http(
    client: TestClient, scoped: None, scope: str
) -> None:
    assert (
        client.post(
            "/api/items/1/approve", json={"actor": "x"}, headers=_bearer(TOKENS[scope])
        ).status_code
        == 403
    )


def test_a_refused_scope_is_403_and_not_401(client: TestClient, scoped: None) -> None:
    """401 sends an operator to rotate a secret; 403 sends them to the scope table."""
    assert client.post("/api/sync", json={}, headers=_bearer(TOKENS["read"])).status_code == 403


def test_the_propose_credential_reaches_the_ingress_it_exists_for(
    client: TestClient, scoped: None, deploy_payload
) -> None:
    """Not merely 'not 403' -- the record is actually created, so the scope is usable."""
    response = client.post(
        "/api/deploy-changes", json=deploy_payload(), headers=_bearer(TOKENS["propose"])
    )
    assert response.status_code == 201
    assert response.json()["source"] == "deploy"


def test_the_observe_credential_cannot_propose(
    client: TestClient, scoped: None, deploy_payload
) -> None:
    """The two writes are separate scopes, not one 'machine may write' scope."""
    assert (
        client.post(
            "/api/deploy-changes", json=deploy_payload(), headers=_bearer(TOKENS["observe"])
        ).status_code
        == 403
    )


def test_the_read_credential_can_read_records_but_not_handoff_briefs(
    client: TestClient, scoped: None
) -> None:
    """`read` is an enumerated list, not 'every GET'.

    A handoff brief is written for an agent holding production infrastructure tools; no narrow
    consumer needs one, and GET/POST on that path share a template.
    """
    assert client.get("/api/items", headers=_bearer(TOKENS["read"])).status_code == 200
    assert client.get("/api/items/1/handoff", headers=_bearer(TOKENS["read"])).status_code == 403


def test_the_read_credential_cannot_patch_the_item_it_may_read(
    client: TestClient, scoped: None
) -> None:
    """This is what makes METHOD part of the key load-bearing rather than merely tidy.

    `GET /api/items/{item_id}` is in `read`; `PATCH` on the SAME template writes `pr_url` and
    records a `pr_linked` event. A template-only allowlist — which is literally the shape the
    orchestrator's `_confine_observer` uses, and which this design was told to copy — would hand
    the write over with the read.
    """
    assert (
        client.patch(
            "/api/items/1", json={"pr_url": "http://x"}, headers=_bearer(TOKENS["read"])
        ).status_code
        == 403
    )


def test_a_value_configured_for_two_scopes_resolves_to_the_narrower_one(
    client: TestClient,
) -> None:
    """Sharing a value between scopes is not expected; resolving it must still fail closed.

    The orchestrator already shares one bearer value between two credentials deliberately, so a
    collision here is not unthinkable — and left to dict ordering it would silently resolve to
    whichever was inserted last.
    """
    import app.auth as auth

    before = (auth.settings.m2m_token, auth.settings.m2m_token_read)
    auth.settings.m2m_token = "shared"
    auth.settings.m2m_token_read = "shared"
    try:
        # `read` may list items, and must NOT inherit full's ability to approve.
        assert client.get("/api/items", headers=_bearer("shared")).status_code == 200
        assert (
            client.post(
                "/api/items/1/approve", json={"actor": "x"}, headers=_bearer("shared")
            ).status_code
            == 403
        )
    finally:
        auth.settings.m2m_token, auth.settings.m2m_token_read = before


def test_the_full_credential_is_unchanged(client: TestClient, scoped: None) -> None:
    """Eight consumers hold it. None of their behaviour may change."""
    assert client.get("/api/items", headers=_bearer(FULL_TOKEN)).status_code == 200
    # A decision route: reached (404 for a missing item), never refused on scope.
    assert (
        client.post(
            "/api/items/999/approve", json={"actor": "x"}, headers=_bearer(FULL_TOKEN)
        ).status_code
        == 404
    )


# --- the empty-bearer fail-open, which is how a map like this goes wrong ----------------------


def test_an_unset_scope_secret_grants_nothing(client: TestClient) -> None:
    """With only the full token configured, an empty bearer must not resolve to a narrow scope.

    `Authorization: Bearer ` strips to `""`, so a map built without a falsy check would bind the
    empty string to whichever scope was left unconfigured -- and every deployment configures only
    some of them.
    """
    import app.auth as auth

    before = (
        auth.settings.m2m_token,
        auth.settings.m2m_token_read,
        auth.settings.m2m_token_propose,
        auth.settings.m2m_token_observe,
    )
    auth.settings.m2m_token = FULL_TOKEN
    auth.settings.m2m_token_read = ""
    auth.settings.m2m_token_propose = ""
    auth.settings.m2m_token_observe = ""
    try:
        # The map itself must not contain an entry for the empty string. Asserted DIRECTLY, not
        # only through a request: a mutation pass showed the request-level assertions below stay
        # green when this falsy check is removed, because `require_m2m` has its own `if token`
        # guard that short-circuits first. Two guards, and without this line only one of them is
        # tested -- so removing the outer one later would silently expose the inner one.
        assert "" not in auth._token_scopes()
        assert auth._token_scopes() == {FULL_TOKEN: "full"}

        assert client.get("/api/items", headers={"Authorization": "Bearer "}).status_code == 401
        assert client.get("/api/items", headers={"Authorization": "Bearer"}).status_code == 401
        assert client.get("/api/items").status_code == 401
    finally:
        (
            auth.settings.m2m_token,
            auth.settings.m2m_token_read,
            auth.settings.m2m_token_propose,
            auth.settings.m2m_token_observe,
        ) = before


def test_the_read_scope_can_reach_the_deploy_policy(client, scoped, db):
    """ADR-0019 increment 5. The landing party reads its conditions from here.

    Without this the route is reachable only by the full bearer, so the orchestrator would
    have to hold the widest credential this service has in order to ask what a human had
    pinned — which is the shape increment 4's split exists to prevent. The control is the
    line below: an unrecognised bearer still gets nothing.
    """
    assert client.get("/api/deploy-policy", headers=_bearer(TOKENS["read"])).status_code == 200
    assert client.get("/api/deploy-policy", headers=_bearer("not-a-token")).status_code == 401


def test_the_read_scope_can_reach_the_policy_at_the_path_the_lander_can_spell(client, scoped, db):
    """ADR-0038. The second projection needs its own entry, and it is easy to leave out.

    Increment 4's producer reads the rule from this document with a READ-scoped credential, and
    the landing party reads it from the path below because it cannot spell the other one. An entry
    covering one path does not cover the other -- `SCOPE_ROUTES` is keyed on (method, template) --
    so a route added without one is reachable by the full bearer alone, which is the shape the
    scope split exists to prevent. The control is the second line: an unrecognised bearer still
    gets nothing, so the 200 above is authorization rather than an open route.
    """
    assert client.get("/api/landing-policy", headers=_bearer(TOKENS["read"])).status_code == 200
    assert client.get("/api/landing-policy", headers=_bearer("not-a-token")).status_code == 401


def test_no_narrow_scope_can_reach_the_deploy_policy_with_a_write(client, scoped):
    """It is a GET and only a GET; the method is part of the key."""
    for token in TOKENS.values():
        assert client.post("/api/deploy-policy", headers=_bearer(token)).status_code in (403, 405)


def test_the_caller_chosen_exception_is_exactly_the_five_routes_that_cannot_pick_a_status() -> None:
    """`CALLER_CHOSEN_STATUS_ROUTES` states a judgment, so it needs its own cross-check.

    A mutation caught this: emptying it left every scope test green, because an empty set
    trivially satisfies "intersects nothing" — the identical failure this module already
    records for `STATUS_MOVING_ROUTES`, reproduced one constant later by the fix for it. A
    derived set is not self-guarding just because it is derived; what is derived is its
    CONTENT, and what needs pinning is the size and direction of the subtraction.

    ADR-0019 increment 5b widened it from one route to two and ADR-0022 to three, and the test's
    NAME moved each time — this module's own recorded lesson is that a name is a behavioural claim.
    The first three each take a FACT and let the server decide what follows; a member that took a
    status would break the property rather than extend the list.

    ADR-0026's work-proposal ingress is the fourth, and it is narrow for a DIFFERENT reason, which
    is why the name no longer says "fact-shaped". The other three compute an outcome the caller
    cannot pick. This one computes nothing: `status="pending"` is a literal in the constructor and
    the route has no other write, so the set of statuses reachable through it has one member. Both
    routes are unable to let a caller choose; only one of them is deciding anything.

    ADR-0029's work retirement is the fifth and returns to the fact-shaped kind: an observation in,
    `resolved` out, and no field by which a caller could ask for anything else.
    """
    exception = STATUS_MOVING_ROUTES - CALLER_CHOSEN_STATUS_ROUTES
    assert exception == {
        ("POST", "/api/deploy-changes"),
        ("POST", "/api/items/{item_id}/deploy-retirement"),
        ("POST", "/api/items/{item_id}/deploy-observation"),
        ("POST", "/api/work-changes"),
        ("POST", "/api/items/{item_id}/work-retirement"),
    }, f"the exception is no longer exactly the five routes it names: {sorted(exception)}"
    assert CALLER_CHOSEN_STATUS_ROUTES < STATUS_MOVING_ROUTES
    assert len(CALLER_CHOSEN_STATUS_ROUTES) == len(STATUS_MOVING_ROUTES) - 5


def test_the_propose_credential_reaches_the_deploy_retirement_it_exists_for(
    client: TestClient, scoped: None, deploy_payload, db
) -> None:
    """ADR-0019 increment 5b. Not merely 'not 403' -- the record actually moves.

    The producer that enumerates waiting pull requests is the only thing positioned to see one
    closed unmerged, and until this it could do nothing about it: `resolve` is the full
    credential's, and the full credential is what task zero exists to keep out of unattended jobs.
    """
    item = client.post(
        "/api/deploy-changes", json=deploy_payload(), headers=_bearer(TOKENS["propose"])
    ).json()
    response = client.post(
        f"/api/items/{item['id']}/deploy-retirement",
        json={
            "observation": "pull_request_closed_unmerged",
            "pull_request_number": item["pull_request_number"],
            "actor": "change-proposer",
        },
        headers=_bearer(TOKENS["propose"]),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


@pytest.mark.parametrize("scope", ["read", "observe"])
def test_the_other_narrow_credentials_cannot_retire_a_deploying_merge(
    client: TestClient, scoped: None, scope: str
) -> None:
    """The control. Without it the test above proves only that SOME credential works."""
    response = client.post(
        "/api/items/1/deploy-retirement",
        json={
            "observation": "pull_request_closed_unmerged",
            "pull_request_number": 42,
            "actor": "x",
        },
        headers=_bearer(TOKENS[scope]),
    )
    assert response.status_code == 403


def test_the_propose_credential_reaches_the_work_retirement_it_exists_for(
    client: TestClient, scoped: None, db
) -> None:
    """ADR-0029. Not merely 'not 403' -- the record actually moves.

    The record must be APPROVED first, because that is the only state the work lane's producer
    ever sees one in, and a retirement from `pending` would be retiring work nobody asked for.
    Approval is the full credential's, deliberately: this test uses it to build the subject and
    the narrow credential to act on it, which is the split the whole file exists to assert.
    """
    proposal = {
        "package_id": "infraops-mcp-server-npm-eslint",
        "package_revision": 1,
        "package_source_repository": "AlobarQuest/intent-packages",
        "risk": "caution",
        "reasoning": "the bump a human approved",
        "actor": "test",
    }
    item = client.post("/api/work-changes", json=proposal, headers=_bearer(FULL_TOKEN)).json()
    client.post(
        f"/api/items/{item['id']}/approve",
        json={"actor": "devon"},
        headers=_bearer(FULL_TOKEN),
    )
    response = client.post(
        f"/api/items/{item['id']}/work-retirement",
        json={
            "observation": "work_unit_completed",
            "package_id": item["package_id"],
            "package_revision": item["package_revision"],
            "actor": "work-watcher",
        },
        headers=_bearer(TOKENS["propose"]),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


@pytest.mark.parametrize("scope", ["read", "observe"])
def test_the_other_narrow_credentials_cannot_retire_work(
    client: TestClient, scoped: None, scope: str
) -> None:
    """The control. Without it the test above proves only that SOME credential works."""
    response = client.post(
        "/api/items/1/work-retirement",
        json={
            "observation": "work_unit_completed",
            "package_id": "whatever",
            "package_revision": 1,
            "actor": "x",
        },
        headers=_bearer(TOKENS[scope]),
    )
    assert response.status_code == 403


def test_the_observe_credential_reaches_the_settlement_it_exists_for(
    client: TestClient, scoped: None, deploy_payload, db
) -> None:
    """ADR-0022. Not merely 'not 403' -- the record actually moves, on the observe scope.

    The watcher is the only thing positioned to see a rollout confirm, and until this it could do
    nothing about it: `resolve` is the full credential's. It never names a status; the server
    derives the verdict from the coordinates and settles on that.
    """
    item = client.post(
        "/api/deploy-changes", json=deploy_payload(), headers=_bearer(TOKENS["propose"])
    ).json()
    response = client.post(
        f"/api/items/{item['id']}/deploy-observation",
        json=_confirmed_rollout(item["pull_request_number"]),
        headers=_bearer(TOKENS["observe"]),
    )
    assert response.status_code == 201
    assert response.json()["item_status"] == "resolved"


@pytest.mark.parametrize("scope", ["read", "propose"])
def test_the_other_narrow_credentials_cannot_observe(
    client: TestClient, scoped: None, scope: str
) -> None:
    """The control. Without it the test above proves only that SOME credential works — and since
    the observation ingress now moves a status, that matters more than it did."""
    response = client.post(
        "/api/items/1/deploy-observation",
        json=_confirmed_rollout(42),
        headers=_bearer(TOKENS[scope]),
    )
    assert response.status_code == 403


def _confirmed_rollout(pull_request_number: int) -> dict:
    """A rollout that confirmed the merged commit is what production reported."""
    return {
        "target_repository": "AlobarQuest/change-manager",
        "pull_request_number": pull_request_number,
        "merge_commit_sha": "2ba9f7f2ef4121aef69153fc2e6dd248cfdcf33b",
        "merged_at": "2026-08-13T08:55:00+00:00",
        "workflow_path": ".github/workflows/deploy.yml",
        "workflow_revision": "a47d4b187c93971a5b5915ce87a963bd4ef35e30",
        "workflow_attestation": "revision_confirmed",
        "rollout_job": "build-and-deploy",
        "rollout_job_conclusion": "success",
        "trigger_step": "Trigger Coolify redeploy",
        "trigger_step_conclusion": "success",
        "run_id": 31685940716,
        "run_attempt": 1,
        "run_url": "https://github.com/AlobarQuest/change-manager/actions/runs/31685940716",
        "run_conclusion": "success",
        "run_concluded_at": "2026-08-13T09:00:00+00:00",
        "observed_at": "2026-08-13T09:20:13+00:00",
        "actor": "deploy-watcher",
    }


def test_the_propose_credential_still_cannot_resolve_anything_else(
    client: TestClient, scoped: None
) -> None:
    """Retirement is narrower than `resolve` on purpose: ONE source each, one outcome each, and
    a fact rather than a status. ADR-0029 adds a second retirement and does not widen this: two
    routes that each retire one source are not the general verb, which reaches every pipeline."""
    response = client.post(
        "/api/items/1/resolve", json={"actor": "producer"}, headers=_bearer(TOKENS["propose"])
    )
    assert response.status_code == 403
