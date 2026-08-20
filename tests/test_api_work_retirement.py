"""POST /api/items/{id}/work-retirement — a work record whose work is done (ADR-0029).

The route exists because a `work` record recorded a human's decision that a bump should be built,
and nothing moved it out of `approved` when the build finished. Production item 61 is the live
case: `infraops-mcp-server-npm-eslint` revision 1, whose unit completed and whose pull request
merged on 2026-08-19, still `approved` the next morning.

THREE PROPERTIES CARRY IT, and each gets a control rather than an assertion alone.

**The caller supplies a FACT, not a status** — which is why the narrow `propose` credential may
reach it. The scope tests state that half.

**The route is one-directional.** It can only ever REMOVE permission, which is what makes it
acceptable on an observation this service has no way to check and never will: change-manager has
no orchestrator egress. Stated below in outcome terms over every starting status, rather than by
trusting the implementation to have one branch.

**It acts on COMPLETION and declines every neighbouring fact.** A failed unit may be retried and a
cancelled one is a human's decision, so the vocabulary has exactly one member and a caller cannot
widen it.
"""

from datetime import UTC, datetime

import pytest

from app.models import ChangeEvent, ChangeItem
from app.work_retirement import RETIRED_EVENT, RETIRED_STATUS, WORK_UNIT_COMPLETED

_PACKAGE = "infraops-mcp-server-npm-eslint"
_REVISION = 1


def _proposal(**overrides) -> dict:
    return {
        "package_id": _PACKAGE,
        "package_revision": _REVISION,
        "package_source_repository": "AlobarQuest/intent-packages",
        "risk": "caution",
        "reasoning": "eslint 10.8.1; the human approved building it",
        "actor": "test",
        **overrides,
    }


@pytest.fixture()
def record(client, m2m):
    """An APPROVED work record, which is the only state the producer ever sees one in.

    Approved rather than pending on purpose: the carry selects on `status=approved`, so a record
    the watcher can see has been through the human gate. A fixture that left it `pending` would
    exercise a state the live lane never presents.
    """
    item = client.post("/api/work-changes", json=_proposal(), headers=m2m).json()
    client.post(f"/api/items/{item['id']}/approve", json={"actor": "devon"}, headers=m2m)
    return item


def _retire(client, m2m, item_id, **overrides):
    body = {
        "observation": WORK_UNIT_COMPLETED,
        "package_id": _PACKAGE,
        "package_revision": _REVISION,
        "actor": "work-watcher",
        **overrides,
    }
    return client.post(f"/api/items/{item_id}/work-retirement", json=body, headers=m2m)


def test_a_record_whose_work_completed_is_retired(client, m2m, record, db):
    """`decided_at` must MOVE, which is not the same as being set.

    The fixture approves the record, so approval has already stamped both decision columns. A
    control asserting `decided_at is not None` therefore passes on the APPROVAL's timestamp and
    says nothing about the retirement — demonstrated, by a mutation deleting the assignment and
    surviving. Pinning it to a sentinel is what makes the assertion about this write.
    """
    item = db.get(ChangeItem, record["id"])
    assert item is not None
    stale = datetime(2000, 1, 1, tzinfo=UTC)
    item.decided_at = stale
    db.commit()

    response = _retire(client, m2m, record["id"])
    assert response.status_code == 200
    assert response.json()["status"] == RETIRED_STATUS

    db.refresh(item)
    assert item.status == RETIRED_STATUS
    assert item.decided_by == "work-watcher"
    assert item.decided_at is not None and item.decided_at.replace(tzinfo=UTC) > stale


def test_the_event_says_why_and_names_the_package_revision(client, m2m, record, db):
    """A machine resolving a decision a human made is only honest if the chain says so."""
    _retire(client, m2m, record["id"])
    events = db.query(ChangeEvent).filter(ChangeEvent.item_id == record["id"]).all()
    retired = [e for e in events if e.event_type == RETIRED_EVENT]
    assert len(retired) == 1
    assert retired[0].from_status == "approved"
    assert retired[0].to_status == RETIRED_STATUS
    assert retired[0].detail is not None
    assert _PACKAGE in retired[0].detail and "revision 1" in retired[0].detail


def test_a_repeat_retirement_is_a_replay_and_not_a_finding(client, m2m, record, db):
    """The watcher sweeps every pass. A retirement it already made must not error."""
    assert _retire(client, m2m, record["id"]).status_code == 200
    second = _retire(client, m2m, record["id"])
    assert second.status_code == 200
    assert second.json()["status"] == RETIRED_STATUS

    events = db.query(ChangeEvent).filter(ChangeEvent.item_id == record["id"]).all()
    assert len([e for e in events if e.event_type == RETIRED_EVENT]) == 1


def test_a_wontfix_record_is_left_exactly_as_a_human_left_it(client, m2m, record, db):
    """`wontfix` is a human's decision and `resolved` is not an upgrade of it.

    Item 60 is the live case: a zod bump a human declined by hand. A watcher that later found a
    completed unit for some other reason must not overwrite that judgment.
    """
    item = db.get(ChangeItem, record["id"])
    assert item is not None
    item.status = "wontfix"
    item.decided_by = "devon"
    db.commit()

    assert _retire(client, m2m, record["id"]).status_code == 200
    db.refresh(item)
    assert item.status == "wontfix" and item.decided_by == "devon"


def test_a_different_package_revision_is_refused_rather_than_ignored(client, m2m, record, db):
    """The locator is what makes the retirement about a subject somebody observed.

    Without this the route retires whichever record an item id happened to select, so a producer
    that resolved the wrong identifier one step earlier closes a record nobody looked at.
    """
    response = _retire(client, m2m, record["id"], package_revision=7)
    assert response.status_code == 409
    assert "revision 7" in response.json()["detail"]

    item = db.get(ChangeItem, record["id"])
    assert item is not None and item.status != RETIRED_STATUS


def test_a_different_package_id_is_refused_rather_than_ignored(client, m2m, record, db):
    """The other half of the locator, and it needs its own case.

    A guard written as `package_id != x or package_revision != y` passes this file with either
    clause deleted unless both are exercised — the two-caller-derived-fields kill, one field over.
    """
    response = _retire(client, m2m, record["id"], package_id="some-other-package")
    assert response.status_code == 409
    assert "some-other-package" in response.json()["detail"]

    item = db.get(ChangeItem, record["id"])
    assert item is not None and item.status != RETIRED_STATUS


def test_an_observation_outside_the_vocabulary_is_refused(client, m2m, record, db):
    """The vocabulary has one member because the outcome cannot be chosen.

    `work_unit_failed` is the shape that matters: a failed unit may still be retried, so a route
    that accepted it would terminate a record whose work is still live.
    """
    response = _retire(client, m2m, record["id"], observation="work_unit_failed")
    assert response.status_code == 409

    item = db.get(ChangeItem, record["id"])
    assert item is not None and item.status != RETIRED_STATUS


def test_a_deploy_record_cannot_be_retired_by_this_route(client, m2m, deploy_payload, db):
    """One source only, which is half of why a narrow credential may hold this.

    The deploy source has its OWN retirement with its own observation vocabulary, so the two must
    not be interchangeable: a caller reaching this route with a deploying merge is refused here
    rather than closed on a fact about a different pipeline.
    """
    item = client.post("/api/deploy-changes", json=deploy_payload(), headers=m2m).json()
    response = _retire(client, m2m, item["id"])
    assert response.status_code == 409
    assert "'deploy' change" in response.json()["detail"]

    stored = db.get(ChangeItem, item["id"])
    assert stored is not None and stored.status != RETIRED_STATUS


def test_a_drift_record_cannot_be_retired_by_this_route(client, m2m, db):
    """The source guard, exercised where NO other guard can refuse first.

    The drift record carries the same `package_id` and `package_revision` the retirement names, so
    the locator guard cannot fire. Without that, deleting the source guard leaves this test
    passing for a reason unrelated to its name — the mutation the deploying-merge suite recorded
    surviving.
    """
    item = ChangeItem(
        identity="prod::some-rule::abc",
        instance="prod",
        rule_key="some-rule",
        source="security",
        status="pending",
        kind="drift",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        reasoning="something drifted",
        risk="caution",
        package_id=_PACKAGE,
        package_revision=_REVISION,
        plan={},
    )
    db.add(item)
    db.commit()

    response = _retire(client, m2m, item.id)
    assert response.status_code == 409
    db.refresh(item)
    assert item.status == "pending"


def test_the_route_can_reach_exactly_one_status_and_it_removes_permission(client, m2m, db):
    """THE one-directional property, stated in outcome terms.

    Asserted over the statuses actually reached from every starting status a work record can hold,
    rather than by reading the implementation — a second branch added later shows up here as a
    status this set does not contain.
    """
    reached = set()
    for index, start in enumerate(("pending", "approved", "deferred", "resolved", "wontfix")):
        item = ChangeItem(
            identity=f"work::alobarquest/intent-packages::{_PACKAGE}::{100 + index}",
            instance="sds",
            rule_key="work-proposal",
            source="work",
            status=start,
            kind="work_proposal",
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            reasoning="the human approved building it",
            risk="caution",
            plan={},
            package_id=_PACKAGE,
            package_revision=100 + index,
            package_source_repository="AlobarQuest/intent-packages",
        )
        db.add(item)
        db.commit()
        _retire(client, m2m, item.id, package_revision=100 + index)
        db.refresh(item)
        reached.add(item.status)

    assert reached == {RETIRED_STATUS, "wontfix"}
    assert "approved" not in reached and "pending" not in reached


def test_an_unknown_item_is_a_404_and_not_a_silent_success(client, m2m):
    assert _retire(client, m2m, 4242).status_code == 404


def test_the_route_rejects_a_body_it_does_not_understand(client, m2m, record):
    """`extra="forbid"`: a caller that believes it is setting a status should learn so."""
    response = client.post(
        f"/api/items/{record['id']}/work-retirement",
        json={
            "observation": WORK_UNIT_COMPLETED,
            "package_id": _PACKAGE,
            "package_revision": _REVISION,
            "actor": "work-watcher",
            "status": "approved",
        },
        headers=m2m,
    )
    assert response.status_code == 422


def test_the_retirement_is_committed_and_not_merely_flushed(tmp_path):
    """Re-read through a DIFFERENT session, on a database that can tell the difference.

    The shared fixtures in this file cannot: `db` hands the application the SAME session the test
    asserts through, and its engine is in-memory SQLite behind a `StaticPool`, so every session
    built on it reuses one connection and therefore one transaction. A flushed-but-uncommitted row
    is visible to all of them, and a mutation deleting `db.commit()` survives the whole file.

    A file-backed database gives a second connection, which is the only reader that cannot see an
    uncommitted write. `expire_all()` would not do — it defeats the identity map within a session
    and re-SELECTs inside the same open transaction, where the flush is still visible.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.db import Base
    from app.work_retirement import retire_work_change

    engine = create_engine(f"sqlite:///{tmp_path / 'retire.db'}", future=True)
    Base.metadata.create_all(engine)

    with Session(engine) as writer:
        item = ChangeItem(
            identity=f"work::alobarquest/intent-packages::{_PACKAGE}::1",
            instance="sds",
            rule_key="work-proposal",
            source="work",
            status="approved",
            kind="work_proposal",
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            reasoning="the human approved building it",
            risk="caution",
            plan={},
            package_id=_PACKAGE,
            package_revision=_REVISION,
            package_source_repository="AlobarQuest/intent-packages",
        )
        writer.add(item)
        writer.commit()
        item_id = item.id

        assert retire_work_change(
            writer,
            item,
            observation=WORK_UNIT_COMPLETED,
            package_id=_PACKAGE,
            package_revision=_REVISION,
            actor="work-watcher",
        )

    with Session(engine) as reader:
        stored = reader.get(ChangeItem, item_id)
        assert stored is not None and stored.status == RETIRED_STATUS
        events = reader.query(ChangeEvent).filter(ChangeEvent.item_id == item_id).all()
        assert [e.event_type for e in events if e.event_type == RETIRED_EVENT] == [RETIRED_EVENT]


def test_the_return_value_says_whether_the_record_moved(client, m2m, record, db):
    """The function's docstring makes this claim, and the route ignores it — so nothing else does.

    A watcher that counted retirements by trusting a status code would report a replay as a fresh
    one. The distinction is only available here, which is why it is pinned here.
    """
    from app.work_retirement import retire_work_change

    item = db.get(ChangeItem, record["id"])
    assert item is not None

    moved = retire_work_change(
        db,
        item,
        observation=WORK_UNIT_COMPLETED,
        package_id=_PACKAGE,
        package_revision=_REVISION,
        actor="work-watcher",
    )
    assert moved is True

    replayed = retire_work_change(
        db,
        item,
        observation=WORK_UNIT_COMPLETED,
        package_id=_PACKAGE,
        package_revision=_REVISION,
        actor="work-watcher",
    )
    assert replayed is False


def test_a_boolean_revision_is_refused_rather_than_read_as_revision_one(client, m2m, record, db):
    """`strict=True` on the revision, and the reason is `WorkChangeIn`'s.

    Pydantic's lax mode reads `true` as 1. A record for revision 1 exists in most of this file, so
    a lax route would match it and retire a record the caller never named.
    """
    response = _retire(client, m2m, record["id"], package_revision=True)
    assert response.status_code == 422

    item = db.get(ChangeItem, record["id"])
    assert item is not None and item.status != RETIRED_STATUS
