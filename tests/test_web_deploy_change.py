"""A deploying-merge change is legible in the web UI.

It has no infrastructure resource, so every drift-shaped rendering path has to have a
fallback — otherwise the record is "visible" as a row of blanks.
"""

from app.deploy_changes import propose_deploy_change
from app.schemas import DeployChangeIn


def _dev_login():
    import app.web_auth as web_auth

    web_auth.settings.dev_user = "devon@example.com"


def test_the_dashboard_names_the_change_and_offers_the_deploy_filter(db, client, deploy_payload):
    _dev_login()
    propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    html = client.get("/?status=pending&source=deploy").text
    assert "AlobarQuest/change-manager#42" in html
    assert "?source=deploy" in html


def test_the_detail_page_shows_the_criteria_and_the_rollback_plan(db, client, deploy_payload):
    _dev_login()
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    html = client.get(f"/items/{item.id}").text
    assert "Acceptance criteria" in html
    assert "/api/health reports the merged commit within 10 minutes" in html
    assert "Rollback plan" in html
    assert "re-point :main at the previous :&lt;sha&gt;" in html
    assert "https://github.com/AlobarQuest/change-manager/pull/42" in html
    # An empty drift plan renders nothing rather than a column of em-dashes.
    assert "Root cause" not in html


def test_a_human_cannot_approve_a_deploy_change_from_the_gui(db, client, deploy_payload):
    """ADR-0019 increment 5: approval is conformance to a pinned policy, not a click.

    This replaces a test that asserted the opposite, and the swap is deliberate rather than
    a green-making edit. Devon's ruling is that the human act is setting the policy, not
    deciding a change one at a time, so the most natural click is exactly the one that has
    to stop working — and it must fail with a reason on screen, not silently.
    """
    _dev_login()
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    refusal = client.post(f"/items/{item.id}/approve")
    assert refusal.status_code == 409
    assert "approved by policy conformance" in refusal.text
    db.refresh(item)
    assert item.status == "pending"


def test_a_deploy_change_is_still_not_a_dead_end(db, client, deploy_payload):
    """The concern the old approve test was really protecting, kept.

    Nothing will ever claim a deploy record, so without terminal actions it parks where no
    control reaches it. Closing the approve door must not close those too — the vetoes are
    the whole of a human's remaining power over such a record.
    """
    _dev_login()
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))

    detail = client.get(f"/items/{item.id}").text
    assert f"/items/{item.id}/resolve" in detail
    assert f"/items/{item.id}/wontfix" in detail

    row = client.get("/?status=pending&source=deploy").text
    assert f"/items/{item.id}/resolve" in row

    assert client.post(f"/items/{item.id}/wontfix").status_code in (200, 303)
    db.refresh(item)
    assert item.status == "wontfix"


def test_the_detail_heading_does_not_render_the_word_None(db, client, deploy_payload):
    _dev_login()
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    heading = client.get(f"/items/{item.id}").text.split("</h2>")[0].split("<h2>")[1]
    assert "None" not in heading
    assert "AlobarQuest/change-manager#42" in heading


def test_an_approved_drift_item_keeps_its_own_buttonless_page(db, client):
    """The control: this change adds actions for records with no executor, and must
    not add them for records that have one — an approved drift item is claimed by the
    window executor, and offering Resolve would race it."""
    from datetime import UTC, datetime

    from app.models import ChangeItem

    _dev_login()
    now = datetime.now(UTC)
    it = ChangeItem(
        identity="prod::572::db2",
        instance="prod",
        rule_key="572",
        resource_uuid="db2",
        resource_name="pg2",
        risk="safe",
        kind="question",
        reasoning="rule #572",
        plan={},
        status="approved",
        source="drift",
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(it)
    db.commit()
    detail = client.get(f"/items/{it.id}").text
    assert f"/items/{it.id}/resolve" not in detail


def test_a_drift_item_still_renders_its_plan(db, client):
    from datetime import UTC, datetime

    from app.models import ChangeItem

    _dev_login()
    now = datetime.now(UTC)
    it = ChangeItem(
        identity="prod::572::db1",
        instance="prod",
        rule_key="572",
        resource_uuid="db1",
        resource_name="pg1",
        risk="safe",
        kind="question",
        reasoning="rule #572",
        plan={"root_cause": "no TLS"},
        status="pending",
        source="drift",
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(it)
    db.commit()
    html = client.get(f"/items/{it.id}").text
    assert "Root cause" in html and "no TLS" in html
    assert "Acceptance criteria" not in html


def test_a_human_cannot_hand_off_a_deploy_change_from_the_gui(db, client, deploy_payload):
    """The API twin has refused this since increment 1; this door did not.

    Live in production until ADR-0019 increment 5's review found it. The button is merely
    hidden — `_row.html` renders it only when a handoff brief exists — and a proposed change
    has none, so nothing rendered it and nothing refused it either. A hidden button is not a
    closed door.
    """
    _dev_login()
    item, _ = propose_deploy_change(db, DeployChangeIn(**deploy_payload()))
    refused = client.post(f"/items/{item.id}/handoff")
    assert refused.status_code == 409
    assert "no authorized executor" in refused.text
    db.refresh(item)
    assert item.status == "pending"
    assert item.handed_off_at is None
