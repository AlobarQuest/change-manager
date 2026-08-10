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
