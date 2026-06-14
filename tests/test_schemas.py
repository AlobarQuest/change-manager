from app.schemas import SyncRequest


def test_sync_request_parses_an_escalation():
    payload = {
        "generated_at": "2026-06-14T07:00:00Z",
        "source_report": "2026-06-14.json",
        "escalations": [{
            "proposal_id": "572:e4f2022e", "instance": "prod",
            "target": {"provider": "coolify", "resource_type": "database", "uuid": "db1", "name": "pg1"},
            "risk": "safe", "kind": "question", "reasoning": "rule #572",
            "plan": {"root_cause": "x", "steps": ["s"], "infraops_tools": [], "risk": "caution",
                     "rollback": "r", "cm_window_hint": "h", "generated_by": "sonnet"},
            "note": None,
        }],
    }
    req = SyncRequest.model_validate(payload)
    assert req.escalations[0].instance == "prod"
    assert req.escalations[0].target.uuid == "db1"
