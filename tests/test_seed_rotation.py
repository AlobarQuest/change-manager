from app.models import ChangeItem
from app.reconcile import reconcile
from scripts.seed_rotation_deploykey import build_deploykey_sync


def test_build_deploykey_sync_shape():
    req = build_deploykey_sync()
    assert req.source == "rotation"
    assert len(req.escalations) == 1
    e = req.escalations[0]
    assert e.proposal_id.startswith("rotation:")
    assert e.risk == "caution" and e.kind == "question"
    assert "coolify_get_deployment" in e.reasoning


def test_seed_creates_one_rotation_item_idempotently(db):
    req = build_deploykey_sync()
    reconcile(db, req)
    reconcile(db, req)  # idempotent — dedup by identity
    items = db.query(ChangeItem).filter_by(source="rotation").all()
    assert len(items) == 1
    assert items[0].status == "pending"


def test_main_refuses_unsubstituted_placeholder(monkeypatch):
    import pytest
    from scripts import seed_rotation_deploykey as seed
    # Placeholder is still the default; main() must raise BEFORE any network/env access.
    monkeypatch.delenv("CHANGE_MGR_API_BASE", raising=False)
    with pytest.raises(RuntimeError, match="Substitute RESOURCE_UUID"):
        seed.main()
